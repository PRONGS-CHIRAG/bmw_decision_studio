"""Readers for the raw BMW hackathon files (no cleaning here, only reshaping)."""

import pandas as pd

from . import config

US_SCALE = ["I Hate It", "A Failure", "Unsatisfactory", "Satisfactory", "Excellent", "Delightful", "I Love It"]


def load_feedback() -> pd.DataFrame:
    """All three Feedback_Explorer sheets stacked, with snake_case columns."""
    frames = []
    for model, path in config.FEEDBACK_FILES.items():
        df = pd.read_excel(path, sheet_name="Feedback_Explorer")
        df["file_model"] = model
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).rename(columns=config.FEEDBACK_COLUMNS)
    return df


def load_sales() -> pd.DataFrame:
    """Long table: model_group, market, year, volume."""
    frames = []
    for sheet, frame in pd.read_excel(config.SALES_FILE, sheet_name=None).items():
        frame = frame.melt(id_vars=["market", "market_code"], var_name="year", value_name="volume")
        frame["year"] = frame["year"].str.replace("volume_", "").astype(int)
        frame["model_group"] = sheet
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_survey_cn_eu() -> pd.DataFrame:
    """CN_EU_2025 sheet -> long table: attribute, market, model, mean (0-10 scale).

    The sheet stores attribute names on one row and the 'Mean' on the next; the
    market header row is sparse (China spans 2 columns, EU spans 3).
    """
    raw = pd.read_excel(config.SURVEY_FILE, sheet_name="CN_EU_2025", header=None)
    markets = raw.iloc[1, 1:].ffill().map({"China": "CN", "EU": "EU"}).tolist()
    models = [str(m).split()[-1] for m in raw.iloc[2, 1:]]
    rows = []
    attribute = None
    for i in range(2, len(raw)):
        label = raw.iloc[i, 0]
        if label == "Mean":
            for j, (market, model) in enumerate(zip(markets, models), start=1):
                rows.append({"attribute": attribute, "market": market, "model": model,
                             "mean": float(raw.iloc[i, j])})
        else:
            attribute = str(label).strip()
    return pd.DataFrame(rows)


def load_survey_us() -> pd.DataFrame:
    """US_2025 sheet -> long table: attribute, model, scale_point, share.

    Blocks of 9 rows: attribute header, 'Sample total', then 7 scale points.
    Two blocks contain an empty spacer row after 'Sample total'; it is skipped.
    """
    raw = pd.read_excel(config.SURVEY_FILE, sheet_name="US_2025", header=None)
    models = [str(m).strip().split()[-1] for m in raw.iloc[0, 2:]]
    rows, attribute = [], None
    for i in range(len(raw)):
        label, kind = raw.iloc[i, 0], raw.iloc[i, 1]
        if pd.isna(label) and pd.isna(kind):    # spacer row
            continue
        if pd.isna(kind):                       # attribute header row
            attribute = str(label).strip()
            continue
        if label in US_SCALE:
            for j, model in enumerate(models, start=2):
                rows.append({"attribute": attribute, "model": model, "scale_point": label,
                             "scale_rank": US_SCALE.index(label) + 1, "share": float(raw.iloc[i, j])})
    return pd.DataFrame(rows)


def summarise_survey_us(long: pd.DataFrame) -> pd.DataFrame:
    """Top-2-box (Delightful + I Love It), bottom-3-box and mean score (1-7) per attribute/model."""
    def agg(g):
        share = g.set_index("scale_rank")["share"]
        total = share.sum()
        return pd.Series({
            "top2_box": share.loc[[6, 7]].sum() / total,
            "bottom3_box": share.loc[[1, 2, 3]].sum() / total,
            "mean_score": (share * share.index).sum() / total,
        })
    return long.groupby(["attribute", "model"]).apply(agg, include_groups=False).reset_index()
