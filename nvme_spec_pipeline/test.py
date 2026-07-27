
"""
Redmine -> TestRail Mapping Tool
"""

import os,re
import pandas as pd

ROOT_FOLDER = r"C:\Reports"
MAX_DEPTH = 3
OUTPUT_FILE="Ticket_Case_Mapping.xlsx"
FILTER_TICKETS=set()   # e.g. {"12345"}
FILTER_CASES=set()     # e.g. {"C12345"}

REDMINE_PATTERN=re.compile(r"\b\d{4,7}\b")
CASE_PATTERN=re.compile(r"\b[Cc](\d{4,8})\b")

def depth(base,path):
    rel=os.path.relpath(path,base)
    return 0 if rel=="." else rel.count(os.sep)+1

def excel_files(folder,max_depth):
    out=[]
    folder=os.path.abspath(folder)
    for root,dirs,files in os.walk(folder):
        if depth(folder,root)>max_depth:
            dirs[:]=[]
            continue
        for f in files:
            if f.lower().endswith((".xlsx",".xls")) and not f.startswith("~$"):
                out.append(os.path.join(root,f))
    return out

mapping={}
processed=0
rows_scanned=0

for file in excel_files(ROOT_FOLDER,MAX_DEPTH):
    try:
        xl=pd.ExcelFile(file)
        processed+=1
        for sheet in xl.sheet_names:
            df=pd.read_excel(file,sheet_name=sheet,dtype=str)
            for _,row in df.iterrows():
                rows_scanned+=1
                tickets=set()
                cases=set()
                for cell in row:
                    if pd.isna(cell):
                        continue
                    text=str(cell)
                    for m in REDMINE_PATTERN.finditer(text):
                        tickets.add(m.group())
                    for m in CASE_PATTERN.finditer(text):
                        cases.add("C"+m.group(1))
                if FILTER_TICKETS:
                    tickets={t for t in tickets if t in FILTER_TICKETS}
                if FILTER_CASES:
                    cases={c for c in cases if c in FILTER_CASES}
                if tickets and cases:
                    for t in tickets:
                        mapping.setdefault(t,set()).update(cases)
    except Exception as e:
        print("Error:",file,e)

ticket_rows=[]
pair_rows=[]

for t in sorted(mapping,key=int):
    clist=sorted(mapping[t], key=lambda x:int(x[1:]))
    ticket_rows.append({
        "Ticket ID":t,
        "Case IDs":", ".join(clist),
        "Case Count":len(clist)
    })
    for c in clist:
        pair_rows.append({"Ticket ID":t,"Case ID":c})

summary=pd.DataFrame([
    ["Excel Files Processed",processed],
    ["Rows Scanned",rows_scanned],
    ["Tickets Found",len(mapping)],
    ["Unique Case IDs",len({c for s in mapping.values() for c in s})]
],columns=["Metric","Value"])

with pd.ExcelWriter(OUTPUT_FILE,engine="openpyxl") as w:
    pd.DataFrame(ticket_rows).to_excel(w,sheet_name="Ticket_To_Cases",index=False)
    pd.DataFrame(pair_rows).to_excel(w,sheet_name="Ticket_Case_Pairs",index=False)
    summary.to_excel(w,sheet_name="Summary",index=False)

print("Done:",OUTPUT_FILE)
