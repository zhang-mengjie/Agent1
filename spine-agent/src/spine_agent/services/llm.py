"""调用聊天模型，把自然语言收成 JSON 规划。贴图像素由文生图接口生成。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from spine_agent.config import get_settings
from spine_agent.services.jsonutil import extract_json

_TEXTURE_SYSTEM = """你是 Spine 角色贴图规划器。只输出一个 JSON 对象，不要 markdown，不要解释。
角色坐标：脚底中心为原点，x 向右为正，y 向上，单位是像素。站立角色从脚到最高点大约 300 到 460。
每个 part 是一块会单独裁开的碎图，name 必须是英文蛇形，例如 torso、head、arm_l、ear_r。
部件必须互相接上：腿的上端贴住身体下端，头的下端贴住身体上端，手臂贴住身体两侧，耳朵贴住头顶。相邻部件重叠大约 10 到 20 像素，不要留空隙。
shape 只能是 ellipse、roundrect、capsule、polygon。polygon 会画成尖朝上的三角，只用于耳朵、角、喙。
pivot 只能是 center、top、bottom、left、right。手臂和腿用 top，头和耳朵用 bottom，尾巴用 right，躯干用 center。
layer 越大越靠前。建议：尾巴 5，腿 10，身体 20，手臂 30，服饰 35，头 40，耳朵 50。
rotation 是逆时针角度。details 只在文生图失败时当地贴纸使用，cx、cy、w、h 取 0 到 1，cy 从上往下。
每个 part 必须有 prompt：只描述这一块本身的外形和颜色，例如「一条橙色猫尾」。不要写「一只小猫」，不要把整个人物写进去。
parts 数量 6 到 12。颜色用 #RRGGBB。
必须按用户描述的物种、配色和配件来画。描述里没有的器官不要加：没提尾巴就不要 tail，没提耳朵就不要 ear，没提围巾就不要 scarf。机器人用方头、天线、身体和四肢，主色跟描述走。
另外给一个 style，一句话，只写共用画风和配色，例如「扁平卡通，橙色毛皮，蓝色围巾，干净描边」。不要在 style 里要求再画一整只角色。
JSON 形状：
{"title":"短标题","style":"扁平二次元，干净描边","parts":[{"name":"torso","prompt":"橙色椭圆身体，正面，浅色肚皮","shape":"ellipse","w":140,"h":150,"fill":"#e09a45","stroke":"#b8742a","pivot":"center","layer":20,"x":0,"y":160,"rotation":0,"details":[]}]}
"""

_RIG_SYSTEM = """你是 Spine 绑骨规划器。只输出一个 JSON 对象，不要 markdown，不要解释。
用户会给出已经画好的部件（name、中心 x/y、宽高、pivot）。
规则：
1. 必须有 {"name":"root"}，root 没有 parent。
2. 每个部件的 name 必须出现在且只出现在一个骨骼的 part 字段里。
3. 可以加没有 part 的结构骨，例如 hip。除 root 外，没有 part 的骨骼要写世界坐标 x、y（脚底为 0，y 向上）。
4. 带 part 的骨骼不要写 x、y、rotation，程序会把骨骼放到该部件的轴点上。
5. parent 必须是另一个骨骼的 name。典型层级：root → hip → 躯干/腿/尾巴，躯干 → 头/手臂/服饰，头 → 耳朵。
{"bones":[{"name":"root"},{"name":"hip","parent":"root","x":0,"y":90},{"name":"torso","parent":"hip","part":"torso"}]}
"""

_CUT_SYSTEM = """你正在看一张已经画好的角色整图。只输出一个 JSON 对象，不要 markdown，不要解释。
坐标系：图像左上角为原点，x 向右，y 向下，单位是像素。用户会告诉你图像宽高，矩形必须完全落在图像内。
按图中这一只角色的实际像素拆成 6 到 12 个部件。每个矩形只框住该部件，不要框进第二只角色，也不要框大片空白。
关节处相邻矩形重叠 12 到 24 像素，切开后才不会露缝。不要给同一块身体画两个矩形。
name 用英文蛇形。pivot 只能是 center、top、bottom、left、right。手臂和腿用 top，头和耳朵用 bottom，尾巴用 right，躯干和服饰用 center。
layer 越大越靠前。建议：尾巴 5，腿 10，身体 20，手臂 30，服饰 35，头 40，耳朵 50。
只拆图里真的有的部位。描述里没有、图里也没有的器官不要加。
同时给出骨骼父子关系，不要写 x、y、rotation。必须有 root。每个部件的 name 恰好出现在一个骨骼的 part 字段里。
{"parts":[{"name":"torso","x":120,"y":180,"w":200,"h":240,"pivot":"center","layer":20}],"bones":[{"name":"root"},{"name":"hip","parent":"root"},{"name":"torso","parent":"hip","part":"torso"}]}
"""

_ANIM_SYSTEM = """你是 Spine 动画规划器。只输出一个 JSON 对象，不要 markdown，不要解释。
rotate 的 angle、translate 的 x 和 y 都是相对当前 setup 姿势的偏移，不是骨骼的绝对坐标。
时间从 0 开始，单位秒。最后一帧的偏移要回到 0，循环才不会跳。
duration 在 0.6 到 3 之间。最多 3 个动画，名字用英文蛇形。只能使用用户给出的骨骼名，不要动画 root。
每个频道 3 到 9 个关键帧。用用户描述的动作；没说清时至少给一个 idle。
{"animations":{"idle":{"duration":1.6,"bones":{"tail":{"rotate":[{"time":0,"angle":0},{"time":0.8,"angle":18},{"time":1.6,"angle":0}]},"torso":{"translate":[{"time":0,"y":0},{"time":0.8,"y":6},{"time":1.6,"y":0}]}}}}}
"""


def _require_key() -> None:
    if not get_settings().llm_api_key.strip():
        raise ValueError("未配置 LLM_API_KEY。可以先用页面上的「生成内置橙猫示例」。")


def _chat(temperature: float) -> ChatOpenAI:
    cfg = get_settings()
    return ChatOpenAI(
        model=cfg.llm_model,
        temperature=temperature,
        max_tokens=cfg.llm_max_tokens,
        top_p=cfg.llm_top_p,
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        timeout=90,
        max_retries=1,
    )


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                chunks.append(str(block.get("text") or ""))
        return "\n".join(chunks)
    return str(content)


async def _complete_content(system: str, content: object, temperature: float) -> dict:
    _require_key()
    llm = _chat(temperature)
    messages = [SystemMessage(content=system), HumanMessage(content=content)]
    result = await llm.ainvoke(messages)
    try:
        return extract_json(_text(result.content))
    except (ValueError, TypeError) as first_error:
        retry = await llm.ainvoke(
            messages + [HumanMessage(content=f"上次输出无法解析：{first_error}。请只重新输出合法 JSON。")]
        )
        try:
            return extract_json(_text(retry.content))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"模型没有返回可解析的 JSON：{exc}") from exc


async def _complete(system: str, user: str, temperature: float) -> dict:
    return await _complete_content(system, user, temperature)


async def plan_texture(prompt: str) -> dict:
    user = (
        f"角色描述：{prompt}\n"
        "只根据这段描述设计。不要改成猫，不要擅自加耳朵、尾巴或围巾。"
    )
    return await _complete(_TEXTURE_SYSTEM, user, 0.5)


async def plan_cut(prompt: str, width: int, height: int, data_url: str) -> dict:
    text = (
        f"图像尺寸 {width}x{height} 像素。矩形使用这个坐标系。\n"
        f"拆解要求：{prompt}\n"
        "只根据图中这一只角色的像素来框。不要发明图里没有的部位。"
    )
    content = [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    return await _complete_content(_CUT_SYSTEM, content, 0.2)


async def plan_rig(prompt: str, parts: list[dict]) -> dict:
    listing = "\n".join(
        f"- {part['name']}: center=({part['x']},{part['y']}) size={part['w']}x{part['h']} pivot={part['pivot']}"
        for part in parts
    )
    user = f"骨骼描述：{prompt}\n\n已有部件：\n{listing}"
    return await _complete(_RIG_SYSTEM, user, 0.2)


async def plan_animation(prompt: str, bones: list[dict]) -> dict:
    listing = "\n".join(
        f"- {bone['name']} parent={bone.get('parent') or '-'} local=({bone.get('x', 0)},{bone.get('y', 0)}) rot={bone.get('rotation', 0)}"
        for bone in bones
        if bone["name"] != "root"
    )
    user = f"动画描述：{prompt}\n\n可动画的骨骼：\n{listing}"
    return await _complete(_ANIM_SYSTEM, user, 0.3)
