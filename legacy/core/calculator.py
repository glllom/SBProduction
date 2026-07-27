from asyncio import new_event_loop

from .models import *

def calculate(item, components):
    apply_structure_changers(item)
    find_and_replace_hardware(item, components)
    check_if_frame_panel_present(item)
    calculate_panel_dimensions(item)
    calculate_panel_dimension(item)
    calculate_second_panel(item)


    find_and_replace_sheets(item, components)
    find_and_replace_construction(item, components)
    find_and_replace_frames(item, components)

    # print(f"item.bom: {item.bom}", f"item.effective_bom: {item.effective_bom}", sep="\n")

def apply_structure_changers(item):
    # Создаем рабочий BOM для конкретной позиции, начиная с базового BOM продукта
    item.effective_bom = list(item.product.bom)
    # print(item.effective_bom)

    for customizer in item.customizers:
        if customizer.tag.tag in ["structure_changer", "front", "hardware", "color"]:
            # Удаляем компоненты
            skus_to_remove = [c.sku for c in customizer.components_to_remove]
            item.effective_bom = [
                entry for entry in item.effective_bom
                if entry['component'].sku not in skus_to_remove
            ]
            # Добавляем компоненты
            for add_entry in customizer.components_to_add:
                # print(add_entry['component'].sku)
                item.effective_bom.append({
                    'component': add_entry['component'],
                    'tag': add_entry['tag'],
                    'qty': add_entry['qty']
                })




    # print(f"panel dimensions: {item.panel_dimensions}, second panel dimensions: {item.second_panel_dimensions}")

def calculate_panel_dimension(item):
    if item.panel:
        item.panel_dimensions = (item.width + item.product.panel_reduction_width,
                                 item.height + item.product.panel_reduction_height - item.undercut)

def check_if_frame_panel_present(item):
    for entry in item.effective_bom:
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
            # multiply hinges on two
            for entry in item.effective_bom:
                if entry['tag'] == "hinge":
                    entry['qty'] *= 2


def calculate_panel_dimensions(item):
    item.panel_dimensions = (item.width + item.product.panel_reduction_width, item.height + item.product.panel_reduction_height - item.undercut)

def find_and_replace_sheets(item, components):
    for entry in item.effective_bom:
        component = entry['component']


        if entry['tag'] == "cover_material" or component.component_type == "sheet":
            # print(component.sku)
            group = component.group

            # Собираем все доступные листы той же группы и сортируем по (width, length)
            sheets = [c for c in components if c.component_type == "sheet" and c.group == group and c.color == component.color]
            sheets.sort(key=lambda sheet: (sheet.width, sheet.length))
            # print(f"sheets: {[sheet.sku for sheet in sheets]}")
    
            def pick_sheet(dimensions):
                if not dimensions:
                    return None
                w, l = dimensions
                for s in sheets:
                    if s.width >= w and s.length >= l:
                        return s
                return sheets[0]

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
            # print(component.sku, component.group, "is not sheet")
            # Не листовые компоненты переносим без изменений

            item.bom.append({
                'component': component,
                'tag': entry['tag'],
                'qty': entry['qty']
            })

def find_and_replace_frames(item, components):
    def remove_frame():
        item.bom = [entry for entry in item.bom if entry['tag'] != 'frame']
    def pick_frame(wall, compatible_frames):
        if not wall or wall == 0:
            return next((c for c in compatible_frames if
                         c.component_type == "frame" and c.length >= item.height), None)
        return next((c for c in compatible_frames if c.component_type == "frame" and c.width >= wall and c.length >= item.height), None)
    if item.frame:
        base_frame = [entry for entry in item.bom if entry['tag'] == 'frame'][0]
        tag = base_frame['component'].component_type
        qty = base_frame['qty']
        compatible_frames = [component for component in components if component.component_type == "frame"
                             and component.group == base_frame['component'].group]
        compatible_frames.sort(key=lambda frame: (frame.width, frame.length))
        remove_frame()
        frame = pick_frame(item.wall_thickness, compatible_frames)
        if frame:
            item.bom.append({'component': frame, 'tag': tag, 'qty': qty})

def find_and_replace_hardware(item, components):
    # for entry in item.effective_bom:
    #     component = entry['component']
    #     if component.component_type in ["hardware"]:
    #         print(component.name)
    pass

def find_and_replace_construction(item, components):
    for entry in item.bom:
        if entry['tag'] == "construction":
            base_component = entry['component']
            group = base_component.group

            # Собираем все компоненты той же группы
            compatible_components = [c for c in components if c.group == group]

            # Сортировать по width, length, thickness
            compatible_components.sort(key=lambda c: (c.width, c.length, c.thickness))

            # Находит такой, что минимально подходит по размерам.
            # thickness<=item.wall_thickness, width>=item.width-10, length>=item.height
            match = next((c for c in compatible_components if
                          c.thickness <= item.wall_thickness and
                          c.width >= item.width - 10 and
                          c.length >= item.height), None)

            if match:
                entry['component'] = match