"""Fixed column schema for headerless TARGET entry CSV rows.

The 25-column TARGET C-style entry export used in trial checks does not include
headers.  Keep the column positions in this file so future TARGET layout
changes can be handled without touching the importer flow.
"""


TARGET_ENTRY_25_COLUMN_SCHEMA = {
    "frame_number": 0,
    "horse_number": 2,
    "horse_name": 7,
    "sex": 9,
    "age": 10,
    "jockey": 12,
    "weight_carried": 13,
    "body_weight": 16,
    "body_weight_diff": 17,
    "affiliation": 18,
    "trainer": 19,
    "owner": 21,
    "breeder": 22,
}


def get_entry_25_value(row, field_name, default=None):
    """Return a cleaned value from a headerless 25-column entry row."""

    index = TARGET_ENTRY_25_COLUMN_SCHEMA.get(field_name)
    if index is None or not isinstance(row, list) or index >= len(row):
        return default
    value = row[index]
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default
