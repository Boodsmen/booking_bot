"""Parse Excel file and return equipment data for import."""

from pathlib import Path
from typing import Optional

import pandas as pd

from utils.logger import logger


def parse_equipment_excel(file_path: Path) -> tuple[list[dict], list[str]]:
    """
    Parse Excel file with equipment data.

    Expected columns (case-insensitive, flexible naming):
        - name / название / наименование (required)
        - category / категория (required)
        - license_plate / гос номер / номер (optional)
        - requires_photo / фото / требуется фото (optional, default False)

    Returns:
        Tuple of (items_list, errors_list)
    """
    errors: list[str] = []
    items: list[dict] = []

    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        return [], [f"Ошибка чтения файла: {e}"]

    if df.empty:
        return [], ["Файл пустой — нет данных для импорта."]

    # Normalize column names
    col_map: dict[str, Optional[str]] = {
        "name": None,
        "category": None,
        "license_plate": None,
        "requires_photo": None,
    }

    for col in df.columns:
        lower = str(col).strip().lower()
        if lower in ("name", "название", "наименование", "имя",
                      "наименование средства измерения", "наименование объекта"):
            col_map["name"] = col
        elif lower in ("category", "категория", "подразделение", "отдел", "группа"):
            col_map["category"] = col
        elif lower in (
            "license_plate", "гос номер", "госномер", "номер",
            "гос_номер", "license plate", "plate",
        ):
            col_map["license_plate"] = col
        elif lower in (
            "requires_photo", "фото", "требуется фото",
            "требует фото", "photo", "photos",
        ):
            col_map["requires_photo"] = col

    # Validate required columns
    if col_map["name"] is None:
        return [], [
            "Не найден столбец с названием оборудования.\n"
            "Ожидается: «Название» или «Name»."
        ]
    if col_map["category"] is None:
        return [], [
            "Не найден столбец с категорией.\n"
            "Ожидается: «Категория» или «Category»."
        ]

    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel rows start at 1, header is row 1

        name = str(row[col_map["name"]]).strip() if pd.notna(row[col_map["name"]]) else ""
        category = str(row[col_map["category"]]).strip() if pd.notna(row[col_map["category"]]) else ""

        if not name or name == "nan":
            errors.append(f"Строка {row_num}: пустое название — пропущена.")
            continue
        if not category or category == "nan":
            errors.append(f"Строка {row_num}: пустая категория — пропущена.")
            continue

        license_plate = None
        if col_map["license_plate"] is not None and pd.notna(row[col_map["license_plate"]]):
            lp = str(row[col_map["license_plate"]]).strip()
            if lp and lp != "nan" and lp != "-":
                license_plate = lp.upper()

        requires_photo = False
        if col_map["requires_photo"] is not None and pd.notna(row[col_map["requires_photo"]]):
            val = str(row[col_map["requires_photo"]]).strip().lower()
            requires_photo = val in ("да", "yes", "true", "1", "+")

        items.append({
            "name": name,
            "category": category,
            "license_plate": license_plate,
            "requires_photo": requires_photo,
        })

    logger.info(f"Parsed Excel: {len(items)} items, {len(errors)} errors")
    return items, errors
