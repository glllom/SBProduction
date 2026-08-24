import datetime
from typing import Optional, Union
import holidays


def add_israeli_working_days(start_date: Optional[Union[datetime.date, datetime.datetime]], num_working_days: int) -> Optional[datetime.date]:
    """
    Calculates the target date by adding `num_working_days` Israeli business days,
    excluding Israeli weekends (Friday and Saturday) and Israeli holidays.
    Israeli workweek is Sunday through Thursday.
    """
    if not start_date or num_working_days <= 0:
        if isinstance(start_date, datetime.datetime):
            return start_date.date()
        return start_date

    if isinstance(start_date, datetime.datetime):
        current = start_date.date()
    else:
        current = start_date

    il_holidays = holidays.country_holidays('IL')
    added_days = 0
    while added_days < num_working_days:
        current += datetime.timedelta(days=1)
        # In Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        # Weekend in Israel is Friday (4) and Saturday (5)
        if current.weekday() in (4, 5):
            continue
        if current in il_holidays:
            continue
        added_days += 1

    return current
