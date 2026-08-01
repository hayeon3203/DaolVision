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
    g.add_node("node_classify_faceid_scenes", nodes.node_classify_faceid_scenes)

    # Phase 3
    g.add_node("node_generate_ltx_batch", nodes.node_generate_ltx_batch)
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

    # 사람 참조 씬을 LTX_FACEID로 분류한 뒤 배치 생성으로 넘긴다(앵커 없음, 3.2와 동일 배선).
    g.add_edge("node_generate_prompts", "node_classify_faceid_scenes")
    g.add_edge("node_classify_faceid_scenes", "node_generate_ltx_batch")
    g.add_edge("node_generate_ltx_batch", "node_checkpoint_clip_approval")
    # 구형 fan-out 노드는 비-LTX 폴백과 호환성을 위해 유지한다.
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
