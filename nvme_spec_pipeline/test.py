"""
Redmine -> TestRail Mapping Tool

Features
--------
1. Search all Excel files recursively up to a configurable depth.
2. Scan every worksheet.
3. Scan every row and every cell.
4. Detect Redmine Tickets (4-7 digit integers).
5. Detect TestRail Case IDs (C1234 - C12345678).
6. Maintain mapping:
        Ticket -> List of Case IDs
7. Optional filtering.
8. Generate Excel report with:
        - Ticket_To_Cases
        - Ticket_Case_Pairs
        - Summary
"""

import os
import re
from pathlib import Path

import pandas as pd


# ============================================================
# USER CONFIGURATION
# ============================================================

ROOT_FOLDER = r"C:\Reports"

MAX_DEPTH = 5

OUTPUT_FILE = "Ticket_Case_Mapping.xlsx"

# Empty list means no filtering

FILTER_TICKETS = [
    # "12345",
    # "56789"
]

FILTER_CASES = [
    # "C12345",
    # "C54321"
]


# ============================================================
# REGEX
# ============================================================

# Redmine Ticket : 4-7 digit integer
REDMINE_PATTERN = re.compile(r"\b\d{4,7}\b")

# TestRail Case ID : C1234 - C12345678
CASE_PATTERN = re.compile(r"\b[Cc](\d{4,8})\b")

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_depth(base_path: str, current_path: str) -> int:
    """
    Returns current folder depth relative to base folder.
    """

    relative = os.path.relpath(current_path, base_path)

    if relative == ".":
        return 0

    return relative.count(os.sep) + 1


def find_excel_files(folder: str, max_depth: int):
    """
    Recursively find all Excel files up to max_depth.
    """

    excel_files = []

    folder = os.path.abspath(folder)

    for root, dirs, files in os.walk(folder):

        current_depth = get_depth(folder, root)

        # Don't traverse beyond required depth
        if current_depth > max_depth:
            dirs[:] = []
            continue

        for file in files:

            if file.startswith("~$"):
                continue

            if file.lower().endswith((".xlsx", ".xls")):
                excel_files.append(os.path.join(root, file))

    return sorted(excel_files)


def normalize_case(case_id: str) -> str:
    """
    Convert case id into standard format.
    Example:
        c12345 -> C12345
    """

    case_id = case_id.upper().strip()

    if not case_id.startswith("C"):
        case_id = "C" + case_id

    return case_id


def normalize_ticket(ticket: str) -> str:
    """
    Strip unwanted spaces.
    """

    return ticket.strip()


def passes_filter(ticket: str, cases: set) -> bool:
    """
    Returns True if mapping satisfies user filters.
    """

    ticket_ok = True
    case_ok = True

    if FILTER_TICKETS:
        ticket_ok = ticket in FILTER_TICKETS

    if FILTER_CASES:
        case_ok = any(case in FILTER_CASES for case in cases)

    return ticket_ok and case_ok

# ============================================================
# BUILD MAPPING
# ============================================================

def build_mapping(excel_files):
    """
    Scan every Excel, every sheet, every row and every cell.

    Returns:
        mapping = {
            "12345": {"C12345", "C12346"},
            "67890": {"C99999"}
        }

        stats = {
            ...
        }
    """

    mapping = {}

    stats = {
        "files_processed": 0,
        "files_failed": 0,
        "sheets_processed": 0,
        "rows_scanned": 0,
        "ticket_matches": 0,
        "case_matches": 0,
    }

    for excel_file in excel_files:

        print(f"Processing : {excel_file}")

        try:

            workbook = pd.ExcelFile(excel_file)

            stats["files_processed"] += 1

            for sheet in workbook.sheet_names:

                stats["sheets_processed"] += 1

                df = pd.read_excel(
                    excel_file,
                    sheet_name=sheet,
                    dtype=str
                )

                for _, row in df.iterrows():

                    stats["rows_scanned"] += 1

                    tickets = set()
                    cases = set()

                    # ---------------------------------------
                    # Scan every cell in current row
                    # ---------------------------------------
                    for cell in row:

                        if pd.isna(cell):
                            continue

                        text = str(cell)

                        # -----------------------------
                        # Find Redmine Ticket IDs
                        # -----------------------------
                        for match in REDMINE_PATTERN.finditer(text):

                            ticket = normalize_ticket(
                                match.group(0)
                            )

                            tickets.add(ticket)

                        # -----------------------------
                        # Find TestRail Case IDs
                        # -----------------------------
                        for match in CASE_PATTERN.finditer(text):

                            case = normalize_case(
                                "C" + match.group(1)
                            )

                            cases.add(case)

                    stats["ticket_matches"] += len(tickets)
                    stats["case_matches"] += len(cases)

                    # Ignore row if either side missing
                    if not tickets or not cases:
                        continue

                    # Apply optional filters
                    for ticket in tickets:

                        if not passes_filter(ticket, cases):
                            continue

                        mapping.setdefault(ticket, set()).update(cases)

        except Exception as ex:

            stats["files_failed"] += 1

            print(f"Failed : {excel_file}")
            print(ex)
            print("-" * 80)

    return mapping, stats

# ============================================================
# GENERATE OUTPUT EXCEL
# ============================================================

def create_output(mapping, stats):
    """
    Creates an Excel workbook with three sheets:
        1. Ticket_To_Cases
        2. Ticket_Case_Pairs
        3. Summary
    """

    # --------------------------------------------------------
    # Sheet 1 : Ticket -> Case List
    # --------------------------------------------------------

    ticket_rows = []

    for ticket in sorted(mapping.keys(), key=int):

        case_list = sorted(
            mapping[ticket],
            key=lambda x: int(x[1:])
        )

        ticket_rows.append({
            "Ticket ID": ticket,
            "Case IDs": ", ".join(case_list),
            "Case Count": len(case_list)
        })

    ticket_df = pd.DataFrame(ticket_rows)

    # --------------------------------------------------------
    # Sheet 2 : Ticket -> Case Pair
    # --------------------------------------------------------

    pair_rows = []

    for ticket in sorted(mapping.keys(), key=int):

        for case in sorted(
            mapping[ticket],
            key=lambda x: int(x[1:])
        ):

            pair_rows.append({
                "Ticket ID": ticket,
                "Case ID": case
            })

    pair_df = pd.DataFrame(pair_rows)

    # --------------------------------------------------------
    # Sheet 3 : Summary
    # --------------------------------------------------------

    unique_cases = set()

    for values in mapping.values():
        unique_cases.update(values)

    summary_rows = [

        {
            "Metric": "Excel Files Processed",
            "Value": stats["files_processed"]
        },

        {
            "Metric": "Excel Files Failed",
            "Value": stats["files_failed"]
        },

        {
            "Metric": "Worksheets Processed",
            "Value": stats["sheets_processed"]
        },

        {
            "Metric": "Rows Scanned",
            "Value": stats["rows_scanned"]
        },

        {
            "Metric": "Ticket Matches Found",
            "Value": stats["ticket_matches"]
        },

        {
            "Metric": "Case Matches Found",
            "Value": stats["case_matches"]
        },

        {
            "Metric": "Unique Tickets",
            "Value": len(mapping)
        },

        {
            "Metric": "Unique Case IDs",
            "Value": len(unique_cases)
        },

        {
            "Metric": "Ticket-Case Pairs",
            "Value": len(pair_rows)
        }

    ]

    summary_df = pd.DataFrame(summary_rows)

    # --------------------------------------------------------
    # Write Excel
    # --------------------------------------------------------

    with pd.ExcelWriter(
        OUTPUT_FILE,
        engine="openpyxl"
    ) as writer:

        ticket_df.to_excel(
            writer,
            sheet_name="Ticket_To_Cases",
            index=False
        )

        pair_df.to_excel(
            writer,
            sheet_name="Ticket_Case_Pairs",
            index=False
        )

        summary_df.to_excel(
            writer,
            sheet_name="Summary",
            index=False
        )

    print("\n" + "=" * 70)
    print("Output written to:", OUTPUT_FILE)
    print("=" * 70)

# ============================================================
# PRINT SUMMARY
# ============================================================

def print_summary(mapping, stats):
    """
    Print execution summary.
    """

    unique_cases = set()

    for case_set in mapping.values():
        unique_cases.update(case_set)

    print("\n")
    print("=" * 70)
    print("Execution Summary")
    print("=" * 70)

    print(f"Excel Files Processed : {stats['files_processed']}")
    print(f"Excel Files Failed    : {stats['files_failed']}")
    print(f"Worksheets Processed  : {stats['sheets_processed']}")
    print(f"Rows Scanned          : {stats['rows_scanned']}")

    print("-" * 70)

    print(f"Ticket Matches Found  : {stats['ticket_matches']}")
    print(f"Case Matches Found    : {stats['case_matches']}")

    print("-" * 70)

    print(f"Unique Tickets        : {len(mapping)}")
    print(f"Unique Case IDs       : {len(unique_cases)}")

    total_pairs = sum(len(cases) for cases in mapping.values())

    print(f"Ticket-Case Pairs     : {total_pairs}")

    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("Redmine -> TestRail Mapping Tool")
    print("=" * 70)

    print("\nSearching Excel files...\n")

    excel_files = find_excel_files(
        ROOT_FOLDER,
        MAX_DEPTH
    )

    print(f"Excel Files Found : {len(excel_files)}")

    if not excel_files:
        print("\nNo Excel files found.")
        return

    mapping, stats = build_mapping(excel_files)

    if not mapping:
        print("\nNo Ticket/Case mapping found.")
        return

    print_summary(mapping, stats)

    create_output(mapping, stats)

    print("\nCompleted Successfully.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
