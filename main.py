import asyncio
import re

import dotenv
import openai
import streamlit as st

from agents import (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    Runner,
    SQLiteSession,
)
from agents.exceptions import MaxTurnsExceeded
from models import RestaurantContext
from tools import reset_db_data
from my_agents.triage_agent import (
    complaints_agent as routed_complaints_agent,
    menu_agent as routed_menu_agent,
    order_agent as routed_order_agent,
    reservation_agent as routed_res_agent,
    triage_agent,
)

dotenv.load_dotenv()

st.title("🍽️ Korean Food Restaurant Bot")

AGENT_ICONS = {
    "Triage Agent":      "🤖",
    "Menu Agent":        "🍽️",
    "Order Agent":       "🛒",
    "Reservation Agent": "📅",
    "Complaints Agent":  "⚠️",
}

HANDOFF_MESSAGES = {
    "Menu Agent":        "🍽️ 메뉴 전문가에게 연결합니다...",
    "Order Agent":       "🛒 주문 담당자에게 연결합니다...",
    "Reservation Agent": "📅 예약 담당자에게 연결합니다...",
    "Complaints Agent":  "🙏 불편 사항 담당자에게 연결합니다...",
}

AGENT_REGISTRY = {
    triage_agent.name: triage_agent,
    routed_menu_agent.name: routed_menu_agent,
    routed_order_agent.name: routed_order_agent,
    routed_res_agent.name: routed_res_agent,
    routed_complaints_agent.name: routed_complaints_agent,
}

OPTION_KEYWORDS = {
    "첫번째",
    "첫번째요",
    "첫번째입니다",
    "두번째",
    "두번째요",
    "두번째입니다",
    "세번째",
    "세번째요",
    "세번째입니다",
}


def _is_option_follow_up(message: str) -> bool:
    if not message:
        return False
    normalized = re.sub(r"[.!?~]", "", message.strip().lower())
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    if re.fullmatch(r"\d+", compact):
        return True
    if re.fullmatch(r"\d+번[가-힣a-z]*", compact):
        return True
    if compact in OPTION_KEYWORDS:
        return True
    return False


def _starting_agent_for_message(message: str) -> "Agent[RestaurantContext]":
    if _is_option_follow_up(message):
        preferred = AGENT_REGISTRY.get(restaurant_ctx.last_agent_name)
        if preferred and preferred.name != triage_agent.name:
            return preferred
    return triage_agent


RATE_LIMIT_RETRY_ATTEMPTS = 3
RATE_LIMIT_BACKOFF_SECONDS = 1.0

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",
        "restaurant-memory.db",
    )
session = st.session_state["session"]


if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent

if "restaurant_ctx" not in st.session_state:
    st.session_state["restaurant_ctx"] = RestaurantContext()
restaurant_ctx: RestaurantContext = st.session_state["restaurant_ctx"]
if not hasattr(restaurant_ctx, "current_turn_handoffs"):
    restaurant_ctx.current_turn_handoffs = []
    restaurant_ctx.handoffs_since_user_message = 0
    restaurant_ctx.loop_block_reason = None
    restaurant_ctx.last_agent_name = None
    restaurant_ctx.last_user_message = None


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        role = message.get("role")
        if not role:
            continue

        with st.chat_message(role):
            if role == "user":
                st.write(message.get("content", ""))
            elif message.get("type") == "message":
                text_parts = [
                    part.get("text", "")
                    for part in message.get("content", [])
                    if part.get("type") == "output_text"
                ]
                if text_parts:
                    st.write("\n\n".join(text_parts).replace("$", r"\$"))


asyncio.run(paint_history())


async def run_agent(message):
    st.session_state["event_log"] = []
    st.session_state["hook_logs"] = []

    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        st.session_state["text_placeholder"] = text_placeholder

        rate_limit_retries = 0

        async def handle_rate_limit_retry(error_message: str) -> bool:
            nonlocal rate_limit_retries, response, text_placeholder
            rate_limit_retries += 1
            if rate_limit_retries > RATE_LIMIT_RETRY_ATTEMPTS:
                text_placeholder.empty()
                st.error("OpenAI API 속도 제한으로 응답을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
                return False

            wait_seconds = RATE_LIMIT_BACKOFF_SECONDS * rate_limit_retries
            response = ""
            text_placeholder.empty()
            st.info(
                f"OpenAI 속도 제한으로 {wait_seconds:.1f}초 대기 후 재시도합니다... "
                f"({rate_limit_retries}/{RATE_LIMIT_RETRY_ATTEMPTS})"
            )
            await asyncio.sleep(wait_seconds)
            text_placeholder = st.empty()
            return True

        try:
            while True:
                try:
                    restaurant_ctx.last_agent_name = st.session_state["agent"].name
                    stream = Runner.run_streamed(
                        st.session_state["agent"],
                        message,
                        session=session,
                        context=restaurant_ctx,
                    )

                    async for event in stream.stream_events():

                        if event.type == "raw_response_event":
                            if event.data.type == "response.output_text.delta":
                                response += event.data.delta
                                text_placeholder.write(response.replace("$", r"\$"))
                        else:
                            agent_name = st.session_state["agent"].name
                            extra = ""
                            if event.type == "run_item_stream_event":
                                item = event.item
                                item_type = getattr(item, "type", None)
                                if item_type == "tool_call_item":
                                    extra = f" | tool: {getattr(item.raw_item, 'name', '')}"
                                elif item_type == "tool_call_output_item":
                                    extra = f" | tool_output: {str(getattr(item, 'output', ''))[:50]}"
                            st.session_state["event_log"].append(f"{agent_name} , {event.type}{extra}")

                        if event.type == "agent_updated_stream_event":
                            if st.session_state["agent"].name != event.new_agent.name:
                                msg = HANDOFF_MESSAGES.get(
                                    event.new_agent.name,
                                    f"{event.new_agent.name}에 연결됨",
                                )
                                st.write(msg)
                                st.session_state["agent"] = event.new_agent
                                text_placeholder = st.empty()
                                response = ""
                    break
                except openai.RateLimitError as rate_err:
                    should_retry = await handle_rate_limit_retry(str(rate_err))
                    if not should_retry:
                        return
                except openai.APIError as api_err:
                    if getattr(api_err, "status_code", None) == 429:
                        should_retry = await handle_rate_limit_retry(str(api_err))
                        if not should_retry:
                            return
                    else:
                        raise
        except InputGuardrailTripwireTriggered:
            text_placeholder.empty()
            st.write("죄송합니다, 레스토랑 관련 문의만 도와드릴 수 있습니다.")
        except OutputGuardrailTripwireTriggered:
            text_placeholder.empty()
            reason = restaurant_ctx.guardrail_state.last_violation_reason or "안전 지침을 충족하지 못했습니다."
            st.warning(f"답변이 안전 기준을 충족하지 못해 표시하지 않았습니다.\n사유: {reason}")
        except MaxTurnsExceeded:
            text_placeholder.empty()
            st.warning("답변이 10턴 제한을 초과해 중단되었습니다. 질문을 더 구체적으로 적어 다시 시도해주세요.")
        finally:
            st.session_state["agent"] = triage_agent


message = st.chat_input("한식 전문 레스토랑입니다. 무엇을 도와드릴까요?")

if message:
    if "text_placeholder" in st.session_state:
        st.session_state["text_placeholder"].empty()

    starting_agent = _starting_agent_for_message(message)
    st.session_state["agent"] = starting_agent
    restaurant_ctx.last_user_message = message
    restaurant_ctx.handoffs_since_user_message = 0
    restaurant_ctx.current_turn_handoffs.clear()
    restaurant_ctx.loop_block_reason = None
    restaurant_ctx.last_agent_name = starting_agent.name

    with st.chat_message("human"):
        st.write(message)
    asyncio.run(run_agent(message))
    if restaurant_ctx.loop_block_reason:
        st.info(restaurant_ctx.loop_block_reason)
        restaurant_ctx.loop_block_reason = None


# Sidebar
with st.sidebar:

    # ── 대화 초기화 버튼 (최상단) ──────────────────
    if st.button("🔄 대화 초기화", use_container_width=True):
        asyncio.run(session.clear_session())
        reset_db_data()
        del st.session_state["session"]
        st.session_state["agent"] = triage_agent
        st.session_state["restaurant_ctx"] = RestaurantContext()
        st.session_state["handoff_logs"] = []
        st.session_state["event_log"] = []
        st.session_state["hook_logs"] = []
        st.rerun()

    st.divider()

    # ── Agent Status (현재 에이전트) ───────────────
    st.subheader("🤖 Current Agent")
    current_agent = st.session_state.get("agent", triage_agent)
    icon = AGENT_ICONS.get(current_agent.name, "🤖")
    st.markdown(
        f"<div style='background:#1e5c2e;padding:8px 12px;border-radius:6px;font-weight:bold'>"
        f"{icon} {current_agent.name}</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Latest Handoff (접이식, 기본 열림) ─────────
    if restaurant_ctx.handoff_history:
        latest = restaurant_ctx.handoff_history[-1]
        with st.expander("🔄 Latest Handoff", expanded=True):
            st.markdown(f"**To:** {latest.to_agent_name}")
            st.markdown(f"**Reason:** {latest.reason}")
            st.markdown(f"**Type:** {latest.issue_type}")
            st.markdown(f"**Issue:** {latest.issue_description}")

    # ── Agent/Tool 실행 로그 ────────────────────────
    hook_logs = st.session_state.get("hook_logs", [])
    if hook_logs:
        st.divider()
        for entry in hook_logs:
            t = entry["type"]
            if t == "start":
                st.write(f"🚀 **{entry['agent']}** 시작")
            elif t == "tool_start":
                st.write(f"🔧 **{entry['agent']}** 도구 실행 중: `{entry['tool']}`")
            elif t == "tool_end":
                st.write(f"✅ **{entry['agent']}** 도구 완료: `{entry['tool']}`")
                st.code(entry["result"])
            elif t == "handoff":
                st.write(f"🔄 Handoff: **{entry['from']}** → **{entry['to']}**")
            elif t == "end":
                st.write(f"🏁 **{entry['agent']}** 완료")

    st.divider()

    # ── Event Log (Debug) ──────────────────────────
    with st.expander("🔍 Event Log (Debug)"):
        event_log = st.session_state.get("event_log", [])
        if event_log:
            for i, evt in enumerate(event_log, 1):
                st.write(f"{i}. {evt}")
        else:
            st.caption("이벤트 없음")
