"""不调用模型，检查橙猫示例能画出贴图、切开碎图，并写出合法的 Spine JSON。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spine_agent.services.pipeline import apply_animation, apply_rig, apply_texture
from spine_agent.services.rig import setup_world_positions
from spine_agent.services.sample import anim_spec, rig_spec, texture_spec
from spine_agent.services.store import empty_project


def main() -> None:
    directory = Path(tempfile.mkdtemp(prefix="spine-self-"))
    project = empty_project("橙猫")
    project = apply_texture(directory, project, texture_spec(), use_image=False)
    texture = Image.open(directory / "texture.png")
    assert texture.mode == "RGBA"
    assert texture.width > 0 and texture.height > 0
    rects = []
    for part in project["parts"]:
        rect = (part["atlas_x"], part["atlas_y"], part["w"], part["h"])
        for other in rects:
            separated = (
                rect[0] + rect[2] <= other[0]
                or other[0] + other[2] <= rect[0]
                or rect[1] + rect[3] <= other[1]
                or other[1] + other[3] <= rect[1]
            )
            assert separated, (part["name"], rect, other)
        assert rect[0] + rect[2] <= texture.width
        assert rect[1] + rect[3] <= texture.height
        rects.append(rect)
    assert (directory / "assembled.png").is_file()

    project = apply_rig(directory, project, rig_spec())
    pieces = list((directory / "pieces").glob("*.png"))
    assert len(pieces) == len(project["parts"])
    names = {bone["name"] for bone in project["bones"]}
    for bone in project["bones"]:
        if bone.get("parent"):
            assert bone["parent"] in names
    world = setup_world_positions(project["bones"])
    assert world["head"][1] > world["torso"][1]
    assert world["ear_l"][1] > world["head"][1]

    project = apply_animation(directory, project, anim_spec())
    document = json.loads((directory / "character.json").read_text(encoding="utf-8"))
    assert document["skeleton"]["spine"].startswith("4.1")
    assert "idle" in document["animations"] and "wave" in document["animations"]
    assert document["slots"]
    atlas = (directory / "character.atlas").read_text(encoding="utf-8")
    assert atlas.startswith("texture.png\n")
    assert "\n\n" not in atlas.strip()
    for part in project["parts"]:
        assert part["name"] in atlas
    print(f"ok {directory}")
    print(f"parts={len(project['parts'])} bones={len(project['bones'])} texture={texture.size}")


if __name__ == "__main__":
    main()
