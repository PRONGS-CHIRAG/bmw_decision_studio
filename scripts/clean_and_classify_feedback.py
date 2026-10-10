from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'BMW-Data'
OUTPUT_DIR = ROOT / 'data' / 'processed'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORY_KEYWORDS = {
    'drivetrain_performance': [
        'drivetrain', 'drive power', 'driving performance', 'engine', 'performance',
        'efficiency', 'acceleration', 'torque', 'power'
    ],
    'handling_chassis': [
        'handling', 'ride', 'riding', 'chassis', 'steering', 'suspension', 'braking',
        'stability', 'driving dynamics'
    ],
    'interior_comfort': [
        'seat', 'seating', 'comfort', 'cabin', 'headroom', 'legroom', 'rear comfort',
        'noise', 'air conditioning'
    ],
    'interior_design': [
        'interior design', 'cockpit', 'dashboard', 'trim', 'materials', 'look / design',
        'buttons', 'ambient lighting'
    ],
    'exterior_design': [
        'exterior design', 'body equipment', 'look / design', 'styling', 'appearance',
        'grille', 'lighting', 'wheels', 'paint'
    ],
    'infotainment_digital': [
        'touch screen', 'infotainment', 'connecteddrive', 'navigation', 'display',
        'operation', 'voice control', 'apps', 'interface', 'user-friendly'
    ],
    'charging_range': [
        'range', 'charging', 'battery', 'charge', 'electric', 'recharging', 'charging time'
    ],
    'quality_reliability': [
        'defect', 'fault', 'quality', 'reliability', 'rattle', 'leak', 'issues',
        'breakdown', 'warning light'
    ],
    'usability': [
        'difficult to use', 'not user-friendly', 'size not user friendly', 'complex',
        'hard to use', 'confusing', 'operation'
    ],
    'safety': [
        'safety', 'driver assistance', 'parking assist', 'sensor', 'warning', 'active safety'
    ],
    'space_storage': [
        'space', 'storage', 'cargo', 'luggage', 'boot', 'rear space', 'trunk'
    ],
}


def normalize_feedback_type(value: object) -> str:
    if pd.isna(value):
        return 'Unknown'
    text = str(value).strip()
    lowered = text.lower()
    mapping = {
        'likes': 'Positive',
        'like': 'Positive',
        'difficult to use': 'Negative',
        'defect': 'Negative',
        'wants': 'Opportunity',
        'want': 'Opportunity',
    }
    return mapping.get(lowered, text.title())


def infer_category(value: object) -> str:
    if pd.isna(value):
        return 'uncategorized'
    text = str(value).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return 'other'


def build_score(feedback_type: str) -> int:
    mapping = {'Positive': 1, 'Negative': 3, 'Opportunity': 2, 'Unknown': 0}
    return mapping.get(feedback_type, 0)


frames = []
for file_path in sorted(DATA_DIR.glob('*feedback*.xlsx')):
    derivative = file_path.name.split('_')[0].upper()
    df = pd.read_excel(file_path, sheet_name='Feedback_Explorer')

    df = df.rename(columns={
        'ID': 'id',
        'Source': 'source',
        'Brand': 'brand',
        'Sales Description': 'sales_description',
        'Country': 'country',
        'Derivate (e-code)': 'derivative_code',
        'Engine Type': 'engine_type',
        'Feedback Type': 'feedback_type_raw',
        'Customer Feedback': 'customer_feedback',
        'Vfc level2 3 Name': 'vfc_level2_3_name',
        'Vfc level2 Name': 'vfc_level2_name',
        'Vfc level3 Name': 'vfc_level3_name',
    })

    df['derivative'] = derivative
    df['source_file'] = file_path.name
    df['feedback_type'] = df['feedback_type_raw'].apply(normalize_feedback_type)
    df['sentiment'] = df['feedback_type'].map({
        'Positive': 'positive',
        'Negative': 'negative',
        'Opportunity': 'opportunity',
        'Unknown': 'unknown',
    }).fillna('unknown')
    df['category'] = df['vfc_level2_3_name'].apply(infer_category)
    df['priority_score'] = df['feedback_type'].apply(build_score)
    df['customer_feedback_clean'] = (
        df['customer_feedback']
        .fillna('')
        .astype(str)
        .str.replace(r'\s+', ' ', regex=True)
        .str.strip()
    )
    df['country'] = df['country'].fillna('Unknown').astype(str).str.strip()
    df['source'] = df['source'].fillna('Unknown').astype(str).str.strip()
    df = df[
        [
            'id', 'source_file', 'derivative', 'source', 'brand', 'country',
            'sales_description', 'derivative_code', 'engine_type', 'feedback_type',
            'sentiment', 'category', 'customer_feedback_clean', 'vfc_level2_3_name',
            'priority_score'
        ]
    ]
    frames.append(df)

clean_df = pd.concat(frames, ignore_index=True)
clean_df = clean_df.drop_duplicates(subset=['id', 'source_file']).reset_index(drop=True)
clean_df.to_csv(OUTPUT_DIR / 'feedback_cleaned.csv', index=False)

requirements = (
    clean_df.groupby(['derivative', 'category'], as_index=False)
    .agg(
        mentions=('id', 'count'),
        positive_mentions=('sentiment', lambda s: (s == 'positive').sum()),
        negative_mentions=('sentiment', lambda s: (s == 'negative').sum()),
        opportunity_mentions=('sentiment', lambda s: (s == 'opportunity').sum()),
    )
)
requirements['priority_score'] = (
    requirements['negative_mentions'] * 3
    + requirements['opportunity_mentions'] * 2
    + requirements['positive_mentions'] * 1
)
requirements = requirements.sort_values('priority_score', ascending=False).reset_index(drop=True)
requirements.to_csv(OUTPUT_DIR / 'requirements_candidates.csv', index=False)

print(f'Cleaned feedback rows: {len(clean_df)}')
print(f'Requirements candidates: {len(requirements)}')
print('Saved:', OUTPUT_DIR / 'feedback_cleaned.csv')
print('Saved:', OUTPUT_DIR / 'requirements_candidates.csv')
print(requirements.head(10).to_string(index=False))
