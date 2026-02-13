"""Import equipment from .xlsx file: Sheet 1 (equipment), Sheet 2 (cars).

Usage: python scripts/import_data.py
"""

import asyncio
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import delete
from database.db import async_session_maker
from database import crud
from database.models import Equipment, Booking, Category
from utils.logger import logger



def parse_quantity_from_name(name: str) -> tuple[str, int]:
    """Extract trailing '- N шт' from name. Returns (clean_name, quantity)."""
    match = re.search(r'\s*[-–]\s*(\d+)\s*шт\.?\s*$', name, re.IGNORECASE)
    if match:
        qty = int(match.group(1))
        clean_name = name[:match.start()].strip()
        return clean_name, qty
    return name.strip(), 1


async def clear_equipment_data(session):
    """Delete all bookings, equipment, and categories (keep users)."""
    await session.execute(delete(Booking))
    await session.execute(delete(Equipment))
    await session.execute(delete(Category))
    await session.commit()
    print("Cleared: bookings, equipment, categories")


async def import_all():
    data_dir = Path("data")
    xlsx_files = [f for f in data_dir.glob("*.xlsx") if not f.name.startswith("~$")]

    if not xlsx_files:
        print(f"No .xlsx files found in {data_dir.resolve()}")
        return

    # Use first xlsx file found
    xlsx_file = xlsx_files[0]
    print(f"Processing file: {xlsx_file.name}")

    # ---- Step 1: Clear existing data ----
    async with async_session_maker() as session:
        await clear_equipment_data(session)

    # ---- Step 2: Parse Sheet 1 (equipment) ----
    print("\n--- Sheet 1: Equipment ---")
    items_by_category: dict[str, dict[str, dict]] = {}  # category -> name -> {name, qty}

    try:
        df1 = pd.read_excel(xlsx_file, sheet_name=0, header=None, dtype=str)

        # Row 1 = category names in columns 1..N
        category_names = []
        for col_idx in range(1, len(df1.columns)):
            val = df1.iloc[1, col_idx]
            if pd.notna(val) and str(val).strip() and str(val).strip().lower() != 'nan':
                category_names.append((col_idx, str(val).strip()))

        for col_idx, cat_name in category_names:
            items_by_category[cat_name] = {}
            print(f"  [CAT] {cat_name}")

        # Rows 2+ = equipment, each column belongs to its category
        for row_idx in range(2, len(df1)):
            for col_idx, cat_name in category_names:
                cell = df1.iloc[row_idx, col_idx]
                if pd.isna(cell) or str(cell).strip() == '' or str(cell).strip().lower() == 'nan':
                    continue
                raw = str(cell).strip()
                name, qty = parse_quantity_from_name(raw)
                if not name:
                    continue
                cat_items = items_by_category[cat_name]
                if name in cat_items:
                    cat_items[name]["qty"] += qty
                else:
                    cat_items[name] = {"name": name, "qty": qty}

        total_sheet1 = sum(len(v) for v in items_by_category.values())
        print(f"Sheet 1: {len(items_by_category)} categories, {total_sheet1} unique items")

    except Exception as e:
        print(f"ERROR reading sheet 1: {e}")

    # ---- Step 3: Parse Sheet 2 (cars) ----
    print("\n--- Sheet 2: Cars ---")
    cars: dict[str, dict] = {}  # key -> {name, license_plate, qty}

    try:
        df2 = pd.read_excel(xlsx_file, sheet_name=1, header=0, dtype=str)
        cols = df2.columns.tolist()
        # Column B = index 1, Column C = index 2
        if len(cols) >= 3:
            plate_col = cols[1]
            name_col2 = cols[2]
        elif len(cols) >= 2:
            plate_col = cols[0]
            name_col2 = cols[1]
        else:
            plate_col = None
            name_col2 = cols[0]

        for i, row in df2.iterrows():
            raw_name = str(row[name_col2]).strip() if name_col2 else ""
            raw_plate = str(row[plate_col]).strip() if plate_col else ""

            if not raw_name or raw_name.lower() == 'nan':
                continue
            if raw_name.lower() in ('марка/модель', 'наименование', 'название'):
                continue

            plate = raw_plate if raw_plate and raw_plate.lower() != 'nan' else None
            key = plate if plate else raw_name

            if key in cars:
                cars[key]["qty"] += 1
            else:
                cars[key] = {"name": raw_name, "license_plate": plate, "qty": 1}

        print(f"Sheet 2: {len(cars)} unique cars")

    except Exception as e:
        print(f"ERROR reading sheet 2 (skipping): {e}")

    # ---- Step 4: Write to DB ----
    print("\n--- Writing to DB ---")
    total_added = 0
    total_errors = 0

    async with async_session_maker() as session:
        # Sheet 1 items
        for cat_name, cat_items in items_by_category.items():
            try:
                category = await crud.get_or_create_category(session, cat_name)
                for item_data in cat_items.values():
                    try:
                        await crud.create_equipment(
                            session,
                            name=item_data["name"],
                            category=cat_name,
                            category_id=category.id,
                            quantity=item_data["qty"],
                        )
                        total_added += 1
                    except Exception as e:
                        print(f"  ERROR adding '{item_data['name']}': {e}")
                        total_errors += 1
            except Exception as e:
                print(f"  ERROR creating category '{cat_name}': {e}")
                total_errors += 1

        # Sheet 2 cars
        if cars:
            try:
                car_category = await crud.get_or_create_category(session, "Автомобили")
                for car_data in cars.values():
                    try:
                        await crud.create_equipment(
                            session,
                            name=car_data["name"],
                            category="Автомобили",
                            category_id=car_category.id,
                            license_plate=car_data.get("license_plate"),
                            requires_photo=True,
                            quantity=car_data["qty"],
                        )
                        total_added += 1
                    except Exception as e:
                        print(f"  ERROR adding car '{car_data['name']}': {e}")
                        total_errors += 1
            except Exception as e:
                print(f"  ERROR creating 'Автомобили' category: {e}")
                total_errors += 1

    print(f"\n=== DONE ===")
    print(f"Added:  {total_added}")
    print(f"Errors: {total_errors}")

    # ---- Verification ----
    async with async_session_maker() as session:
        from sqlalchemy import select, func
        count_result = await session.execute(select(func.count()).select_from(Equipment))
        eq_count = count_result.scalar()

        qty_result = await session.execute(
            select(Equipment.name, Equipment.quantity)
            .where(Equipment.quantity > 1)
            .order_by(Equipment.quantity.desc())
            .limit(5)
        )
        multi_qty = qty_result.all()

    print(f"\nTotal equipment in DB: {eq_count}")
    if multi_qty:
        print("Top items with quantity > 1:")
        for name, qty in multi_qty:
            print(f"  {name}: {qty}")


if __name__ == "__main__":
    asyncio.run(import_all())
