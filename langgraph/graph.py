"""
전체 그래프 조립.
- SqliteSaver: OpenWebUI가 재시작되거나 사람이 몇 시간 뒤에 승인해도
  thread_id 기준으로 정확히 멈췄던 지점부터 재개 가능하게 함
"""
import aiosqlite
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from state import GraphState
import nodes

# 서버 수명 동안 열린 sqlite 연결을 붙잡아 둔다 (GC로 닫히면 checkpointer가 죽음).
_open_conns: list = []


def _entry_router(state: GraphState) -> str:
    """참조 이미지 미첨부 + 이미지 생성 요청이면 M2 이미지 분기, 아니면 기존 경로."""
    if state.get("image_request") and not state.get("ref_images"):
        return "node_rewrite_image_query"
    return "node_parse_input"


def build_graph():
    g = StateGraph(GraphState)

    # M2 이미지 생성 분기 (앞단 선택적)
    g.add_node("node_rewrite_image_query", nodes.node_rewrite_image_query)
    g.add_node("node_generate_image", nodes.node_generate_image)
    g.add_node("node_checkpoint_image_approval", nodes.node_checkpoint_image_approval)
    g.add_node("node_checkpoint_scenario_input", nodes.node_checkpoint_scenario_input)

    # Phase 1
    g.add_node("node_parse_input", nodes.node_parse_input)
    g.add_node("node_split_scenes", nodes.node_split_scenes)
    g.add_node("node_checkpoint_scene_approval", nodes.node_checkpoint_scene_approval)

    # Phase 2
    g.add_node("node_generate_prompts", nodes.node_generate_prompts)

    # Phase 3
    g.add_node("node_generate_one_clip", nodes.node_generate_one_clip)
    g.add_node("node_merge_clip_results", nodes.node_merge_clip_results)
    g.add_node("node_checkpoint_clip_approval", nodes.node_checkpoint_clip_approval)

    # Phase 4
    g.add_node("node_edit_concat", nodes.node_edit_concat)
    g.add_node("node_generate_subtitles", nodes.node_generate_subtitles)
    g.add_node("node_checkpoint_edit_review", nodes.node_checkpoint_edit_review)

    # Phase 5
    g.add_node("node_final_render", nodes.node_final_render)

    # ── 엣지 연결 ──────────────────────────────────────────
    # START 조건 분기: 이미지 생성 요청이면 M2 분기, 아니면 기존 경로
    g.add_conditional_edges(
        START, _entry_router,
        ["node_rewrite_image_query", "node_parse_input"],
    )
    # M2 이미지 분기: rewrite → generate → 승인 게이트(자체 Command 분기)
    g.add_edge("node_rewrite_image_query", "node_generate_image")
    g.add_edge("node_generate_image", "node_checkpoint_image_approval")
    # node_checkpoint_image_approval은 Command(goto=...)로 자체 분기
    # (approve→scenario_input 게이트 / 수정→rewrite)
    # node_checkpoint_scenario_input도 Command(goto=...)로 자체 분기 (시나리오 입력→parse_input)

    g.add_edge("node_parse_input", "node_split_scenes")
    g.add_edge("node_split_scenes", "node_checkpoint_scene_approval")
    # node_checkpoint_scene_approval은 Command(goto=...)로 자체 분기하므로 add_edge 불필요

    # Send API fan-out: node_generate_prompts 다음 바로 conditional_edges의
    # path 함수(node_dispatch_generation)가 list[Send]를 반환하면
    # LangGraph가 자동으로 node_generate_one_clip을 씬 개수만큼 병렬 호출한다.
    # (재생성 루프도 동일 경로를 재진입하므로 별도 노드로 분리하지 않음)
    g.add_conditional_edges(
        "node_generate_prompts",
        nodes.node_dispatch_generation,
        ["node_generate_one_clip"],
    )
    # 재생성 루프(3-3)는 node_checkpoint_clip_approval이 Command(goto=[Send(...), ...])를
    # 직접 반환하므로 여기서 별도 conditional_edges 등록이 필요 없음
    g.add_edge("node_generate_one_clip", "node_merge_clip_results")
    g.add_edge("node_merge_clip_results", "node_checkpoint_clip_approval")
    # node_checkpoint_clip_approval도 Command(goto=...)로 자체 분기

    g.add_edge("node_edit_concat", "node_generate_subtitles")
    g.add_edge("node_generate_subtitles", "node_checkpoint_edit_review")
    # node_checkpoint_edit_review도 Command(goto=...)로 자체 분기

    g.add_edge("node_final_render", END)

    return g


async def compile_graph(sqlite_path: str = "checkpoints.db"):
    conn = aiosqlite.connect(sqlite_path)
    # ponytail: aiosqlite 워커 스레드가 non-daemon이라 driver.py/test_*.py 같은
    # 일회성 스크립트가 PASS 후에도 종료되지 못함 → 시작 전에 daemon 표시.
    # (_thread는 aiosqlite 내부 속성 — 업그레이드 시 이 줄이 깨지면 여기부터 확인)
    conn._thread.daemon = True
    conn = await conn
    _open_conns.append(conn)  # 연결 수명 유지
    checkpointer = AsyncSqliteSaver(conn)
    graph = build_graph().compile(checkpointer=checkpointer)
    return graph
