from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_family_title = State()
    waiting_for_display_name = State()
    answering_test = State()
