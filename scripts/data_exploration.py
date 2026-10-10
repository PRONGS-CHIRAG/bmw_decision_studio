from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

root = Path(__file__).resolve().parents[1]
data_dir = root / 'BMW-Data'
out_path = root / 'data_exploration_summary.json'

summary: dict[str, dict] = {}

for file_path in sorted(data_dir.glob('*.xlsx')):
    workbook_summary: dict[str, dict] = {'sheets': {}}
    excel_file = pd.ExcelFile(file_path)
    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        sheet_summary = {
            'rows': int(len(df)),
            'columns': list(df.columns),
            'null_count': int(df.isna().sum().sum()),
            'dtypes': {str(col): str(dtype) for col, dtype in df.dtypes.items()},
            'sample_rows': df.head(5).to_dict(orient='records'),
        }
        workbook_summary['sheets'][sheet_name] = sheet_summary
    summary[file_path.name] = workbook_summary

out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')

print(f'Wrote summary to: {out_path}')
for filename, workbook in summary.items():
    print(f'\nFILE: {filename}')
    for sheet_name, sheet_info in workbook['sheets'].items():
        print(f"- {sheet_name}: rows={sheet_info['rows']}, cols={len(sheet_info['columns'])}")
        print(f"  columns={sheet_info['columns'][:10]}")
