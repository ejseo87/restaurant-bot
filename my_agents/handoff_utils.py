import streamlit as st
from agents import RunContextWrapper, handoff
from agents.extensions import handoff_filters

from models import HandoffData, RestaurantContext

HANDOFF_MESSAGES = {
    "Menu Agent":        "🍽️ 메뉴 전문가에게 연결합니다...",
    "Order Agent":       "🛒 주문 담당자에게 연결합니다...",
    "Reservation Agent": "📅 예약 담당자에게 연결합니다...",
}


def handle_handoff(_wrapper: RunContextWrapper[RestaurantContext], input_data: HandoffData):
    msg = HANDOFF_MESSAGES.get(input_data.to_agent_name, "담당자에게 연결합니다...")
    if "handoff_logs" not in st.session_state:
        st.session_state["handoff_logs"] = []
    st.session_state["handoff_logs"].append({"msg": msg, "reason": input_data.reason})


def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
    )
