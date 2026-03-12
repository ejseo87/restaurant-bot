import streamlit as st
from agents import RunContextWrapper, handoff
from agents.extensions import handoff_filters

from models import HandoffData, RestaurantContext

HANDOFF_MESSAGES = {
    "Menu Agent":        "🍽️ 메뉴 전문가에게 연결합니다...",
    "Order Agent":       "🛒 주문 담당자에게 연결합니다...",
    "Reservation Agent": "📅 예약 담당자에게 연결합니다...",
    "Complaints Agent":  "🙏 불편 사항 담당자에게 연결합니다...",
}

_PING_PONG_PAIRS = {
    ("Menu Agent", "Order Agent"),
    ("Order Agent", "Menu Agent"),
    ("Order Agent", "Complaints Agent"),
    ("Complaints Agent", "Order Agent"),
}


def handle_handoff(wrapper: RunContextWrapper[RestaurantContext], input_data: HandoffData):
    msg = HANDOFF_MESSAGES.get(input_data.to_agent_name, "담당자에게 연결합니다...")
    if "handoff_logs" not in st.session_state:
        st.session_state["handoff_logs"] = []
    st.session_state["handoff_logs"].append({"msg": msg, "reason": input_data.reason})
    ctx = wrapper.context
    ctx.handoff_history.append(input_data)
    ctx.handoffs_since_user_message += 1
    ctx.current_turn_handoffs.append(input_data.to_agent_name)
    ctx.current_turn_handoffs = ctx.current_turn_handoffs[-4:]
    ctx.last_agent_name = input_data.to_agent_name
    ctx.loop_block_reason = None


def _handoff_guard(target_agent_name: str):
    def _guard(wrapper: RunContextWrapper[RestaurantContext], _agent) -> bool:
        ctx = wrapper.context
        source = ctx.last_agent_name
        if (
            source
            and (source, target_agent_name) in _PING_PONG_PAIRS
            and ctx.handoffs_since_user_message >= 2
        ):
            ctx.loop_block_reason = (
                f"{source}와 {target_agent_name} 사이에서 반복 연결이 감지되어 중단했어요. "
                "필요한 정보를 먼저 물어본 뒤 다시 시도해 주세요."
            )
            return False
        return True

    return _guard


def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
        is_enabled=_handoff_guard(agent.name),
    )
