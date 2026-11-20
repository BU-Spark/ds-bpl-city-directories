"""Source-only review crops and native-box overlays, with no changes to OCR."""

from pathlib import Path
import textwrap

from .io import read_json, sha256_file, write_json
from .manifest import load_manifest
from .quality import column_geometry, line_diagnostics, review_body_y, verify_run


def render_review_images(run_index, manifest_path, destination):
    from PIL import Image, ImageDraw, ImageFont
    index, manifest = read_json(run_index), load_manifest(manifest_path)
    output = Path(destination) / "images"
    output.mkdir(parents=True, exist_ok=True)
    tiles, bands = [], []
    for choice in index["runs"]:
        record, rows, source = verify_run(choice["run_directory"], manifest)
        page, leaf = record["page"], choice["leaf_num"]
        with Image.open(source) as original:
            image = original.convert("RGB")
        width, height = image.size
        top, bottom = review_body_y(page)
        geometry = column_geometry(rows, width, (top, bottom))
        if geometry["status"] != "two_start_clusters":
            raise ValueError("Two-column crop layout unresolved; review this page manually before drawing column bands")
        gutter = round(geometry["gutter_x"])
        left = max(0, round(geometry["left_start_x"] - 70))
        right = min(width, round(max(r["x1"] for r in rows if r["y0"] >= top and r["y1"] <= bottom) + 15))
        flags, _, _ = line_diagnostics(rows, page, geometry)
        thumbnail = image.resize((380, round(height * 380 / width)))
        drawing, scale = ImageDraw.Draw(thumbnail), 380 / width
        for row, flag in zip(rows, flags):
            color = "#999999" if flag["column_candidate"] == "outside_review_body" else (
                "#176dab" if flag["column_candidate"] == "L" else "#e27918")
            if "vertical_symbol_candidate" in flag["review_flags"]:
                color = "#d02b27"
            drawing.rectangle(tuple(round(row[k] * scale) for k in ("x0", "y0", "x1", "y1")), outline=color, width=1)
            if row["reading_order"] % 20 == 0:
                drawing.text((round(row["x0"] * scale), round(row["y0"] * scale)), str(row["reading_order"]),
                             font=ImageFont.load_default(size=12), fill="red", stroke_width=1, stroke_fill="white")
        tile = Image.new("RGB", (400, 700), "white")
        tile.paste(thumbnail, (10, 40))
        ImageDraw.Draw(tile).text((10, 5), f"p{page['printed_page']} / leaf {leaf} / {len(rows)} rows",
                                 font=ImageFont.load_default(size=17), fill="black")
        tiles.append(tile)
        sheet = Image.new("RGB", (1640, 930), "#eeeeee")
        drawing = ImageDraw.Draw(sheet)
        drawing.text((14, 8), f"Source review p{page['printed_page']}, leaf {leaf}: raw crops + native OCR lines intersecting bands",
                     font=ImageFont.load_default(size=20), fill="black")
        positions = (("top", top + 5), ("middle", (top + bottom) // 2 - 55), ("bottom", bottom - 110))
        for ri, (name, y) in enumerate(positions):
            for ci, column in enumerate(("L", "R")):
                x0, x1 = (left, gutter) if column == "L" else (gutter, right)
                box = (x0, y, x1, y + 110)
                ox, oy = 10 + ci * 820, 50 + ri * 290
                drawing.text((ox, oy), f"{column}-{name}, source box {box}", font=ImageFont.load_default(size=16), fill="black")
                sheet.paste(image.crop(box), (ox, oy + 25))
                selected = [r for r in rows if r["y0"] < y + 110 and r["y1"] > y and r["x0"] < x1 and r["x1"] > x0
                            and ((r["x0"] + r["x1"]) / 2 < gutter) == (column == "L")]
                wrapped = [part for r in selected for part in textwrap.wrap(f"[{r['reading_order']}] {r['text']}", width=100)]
                for number, line in enumerate(wrapped[:8]):
                    drawing.text((ox, oy + 144 + number * 16), line, font=ImageFont.load_default(size=14), fill="#20344b")
                if len(wrapped) > 8:
                    drawing.text((ox + 650, oy + 270), "more OCR rows...", font=ImageFont.load_default(size=13), fill="red")
                bands.append({"region_id": f"leaf{leaf:04d}-{column}-{name}", "leaf_num": leaf,
                              "printed_page": page["printed_page"], "bbox": list(box), "gutter_x": gutter,
                              "image_sha256": record["source"]["sha256"],
                              "line_ids": [r["line_id"] for r in selected],
                              "reading_orders": [r["reading_order"] for r in selected],
                              "ocr_lines": [r["text"] for r in selected]})
        sheet.save(output / f"leaf{leaf:04d}_bands.jpg", quality=92)
        image.close()
    for start in range(0, len(tiles), 8):
        overview = Image.new("RGB", (1600, 1400), "#dddddd")
        for position, tile in enumerate(tiles[start:start + 8]):
            overview.paste(tile, ((position % 4) * 400, (position // 4) * 700))
        overview.save(output / f"overview_{start // 8 + 1}.jpg", quality=90)
    write_json(Path(destination) / "bands.json", bands)
    inventory = {p.name: sha256_file(p) for p in sorted(output.glob("*.jpg"))}
    write_json(Path(destination) / "figure_checksums.json", {"renderer_sha256": sha256_file(__file__), "images": inventory,
               "display_note": "Source crops preserve native color and pixels before JPEG report encoding. Overviews are resized overlays. OCR lines remain unchanged; cropped bands are not exhaustive ground truth."})
    return {"page_band_sheets": len(tiles), "spatial_bands": len(bands), "overview_sheets": (len(tiles) + 7) // 8}
