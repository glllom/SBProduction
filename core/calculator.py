from asyncio import new_event_loop

from .models import *

def calculate(item, components):
    check_if_frame_panel_present(item)
    calculate_panel_dimensions(item)
    calculate_panel_dimension(item)
    calculate_second_panel(item)

    find_and_replace_sheets(item, components)

    # print(f"panel dimensions: {item.panel_dimensions}, second panel dimensions: {item.second_panel_dimensions}")

def calculate_panel_dimension(item):
    if item.panel:
        item.panel_dimensions = (item.width + item.product.panel_reduction_width,
                                 item.height + item.product.panel_reduction_height - item.undercut)

def check_if_frame_panel_present(item):
    for entry in item.product.bom:
        component = entry['component']
        if component.component_type == "frame":
            item.frame = True
        if component.component_type == "sheet":
            item.panel = True

def calculate_second_panel(item):
    for customizer in item.customizers:
        if customizer.tag.tag == "double_door_mod":
            old_width = item.panel_dimensions[0]
            new_width =round((old_width * customizer.par1 if customizer.par1 < 1 else customizer.par1) + 1,1)
            item.set_panel_dimensions(new_width, item.panel_dimensions[1])
            item.second_panel_dimensions = (round(old_width - new_width + item.product.double_door_gap,1), item.panel_dimensions[1])
        #

def calculate_panel_dimensions(item):
    item.panel_dimensions = (item.width + item.product.panel_reduction_width, item.height + item.product.panel_reduction_height - item.undercut)

def find_and_replace_sheets(item, components):
    for entry in item.product.bom:
        component = entry['component']

        if component.component_type == "sheet":
            group = component.group

            # Собираем все доступные листы той же группы и сортируем по (width, length)
            sheets = [c for c in components if c.component_type == "sheet" and c.group == group]
            sheets.sort(key=lambda sheet: (sheet.width, sheet.length))
            # print(f"sheets: {sheets}")

            def pick_sheet(dimensions):
                if not dimensions:
                    return None
                w, l = dimensions
                for s in sheets:
                    if s.width >= w and s.length >= l:
                        return s
                return None

            # Для основной панели
            sheet1 = pick_sheet(item.panel_dimensions)
            if sheet1:
                item.bom.append({
                    'component': sheet1,
                    'tag': entry['tag'],
                    'qty': entry['qty']
                })

            # Если есть вторая панель — подбираем лист и для неё
            if item.second_panel_dimensions:
                sheet2 = pick_sheet(item.second_panel_dimensions)
                if sheet2:
                    item.bom.append({
                        'component': sheet2,
                        'tag': entry['tag'],
                        'qty': entry['qty']
                    })
        else:
            # Не листовые компоненты переносим без изменений
            item.bom.append({
                'component': component,
                'tag': entry['tag'],
                'qty': entry['qty']
            })

