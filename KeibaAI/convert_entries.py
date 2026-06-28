import argparse

from importer.entry_converter import convert_to_today_entries


def main() -> None:
    """出走表ファイルを、分析AIが読めるCSVへ変換する入口です。"""

    parser = argparse.ArgumentParser(description="出走表HTML/CSVをtoday_entries.csvへ変換します")
    parser.add_argument("input", help="読み込むHTMLまたはCSVファイル")
    parser.add_argument(
        "--output",
        default="data/today_entries.csv",
        help="変換後のCSV保存先。通常は data/today_entries.csv のままでOKです",
    )
    args = parser.parse_args()

    convert_to_today_entries(args.input, args.output)
    print(f"変換しました: {args.output}")


if __name__ == "__main__":
    main()
