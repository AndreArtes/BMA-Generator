"""
BMA Generator
=============

Generates .BMA configurations (<ID>_ass folders with HQ/MQ/LQ-root.BMA +
thumbnail) from a bm3 export (Excel + .BM3 model folders).

Usage (no argument, guided mode):
    python main.py

Command-line usage:
    python main.py init-roles --bm3-dir "fichier bm3" --roles roles.xlsx
        -> generates a roles.xlsx file to fill in (the "Role" column) for
           products whose anchor role can't be inferred automatically
           (Pouf and Table, which have 2 possible variants).

    python main.py generate --bm3-dir "fichier bm3" --roles roles.xlsx --out-dir "fichier bma"
        -> generates the .BMA files + the output Excel in --out-dir.

Valid roles: central, lateral_left, lateral_right, corner_left,
corner_right, pouf_lateral, pouf_frontal, table_lateral, table_frontal.
"""

import argparse
import sys
from pathlib import Path

from bma_generator import excel_io, generator, templates as tpl


def find_bm3_xlsx(bm3_dir):
    bm3_dir = Path(bm3_dir)
    candidates = [
        p for p in bm3_dir.glob("*.xlsx")
        if not p.name.startswith("~$")
    ]
    if not candidates:
        raise FileNotFoundError(f"No .xlsx file found in {bm3_dir}")
    return candidates[0]


def cmd_init_roles(args):
    bm3_xlsx = find_bm3_xlsx(args.bm3_dir)
    products = excel_io.read_bm3_products(bm3_xlsx)
    excel_io.write_roles_template(products, args.roles)
    n_todo = sum(1 for p in products if not p.inferred_role)
    print(f"Roles file generated: {args.roles}")
    print(f"{len(products)} products, {n_todo} of which need to be filled in manually (marked A_COMPLETER).")
    print(f"Valid roles: {', '.join(tpl.ALL_ROLES)}")


def cmd_generate(args):
    bm3_xlsx = find_bm3_xlsx(args.bm3_dir)
    products = excel_io.read_bm3_products(bm3_xlsx)

    roles_path = Path(args.roles)
    if not roles_path.exists():
        print(f"Roles file not found ({roles_path}).")
        print("Running 'init-roles' to generate it...")
        cmd_init_roles(args)
        print("\nFill in the 'Role' column in the generated file, then run generation again.")
        return

    roles = excel_io.read_roles(roles_path)

    generated, skipped, rows_products, rows_assets, rows_parameters, warnings, products_header = generator.generate(
        products, roles, args.bm3_dir, args.out_dir, brand_override=getattr(args, "brand", None)
    )

    if rows_products:
        out_xlsx = Path(args.out_dir) / "export-products-bma.xlsx"
        generator.write_output_excel(
            rows_products, rows_assets, rows_parameters, bm3_xlsx, out_xlsx, products_header=products_header
        )
        print(f"Output Excel written: {out_xlsx}")

    print(f"{len(generated)} product(s) generated in {args.out_dir}: {', '.join(generated) or '-'}")
    if skipped:
        print(f"{len(skipped)} product(s) skipped (missing or invalid role in {roles_path}): {', '.join(skipped)}")
    for warning in warnings:
        print(f"WARNING: {warning}")


def run_interactive():
    print("=== BMA Generator ===")
    bm3_dir = input("bm3 folder [fichier bm3]: ").strip() or "fichier bm3"
    out_dir = input("bma output folder [fichier bma]: ").strip() or "fichier bma"
    roles_path = input("Roles file [roles.xlsx]: ").strip() or "roles.xlsx"

    class Args:
        pass

    args = Args()
    args.bm3_dir = bm3_dir
    args.out_dir = out_dir
    args.roles = roles_path
    cmd_generate(args)


def main():
    parser = argparse.ArgumentParser(description="Generates .BMA files from a bm3 export.")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init-roles", help="Generates the roles file to fill in.")
    p_init.add_argument("--bm3-dir", default="fichier bm3")
    p_init.add_argument("--roles", default="roles.xlsx")
    p_init.set_defaults(func=cmd_init_roles)

    p_gen = sub.add_parser("generate", help="Generates the .BMA files.")
    p_gen.add_argument("--bm3-dir", default="fichier bm3")
    p_gen.add_argument("--roles", default="roles.xlsx")
    p_gen.add_argument("--out-dir", default="fichier bma")
    p_gen.add_argument("--brand", default=None, help="Fallback value for the Brand column if missing from the bm3 source.")
    p_gen.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if not getattr(args, "command", None):
        run_interactive()
        return
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
