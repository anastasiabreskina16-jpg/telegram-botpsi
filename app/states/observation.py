from aiogram.fsm.state import State, StatesGroup


class ObservationStates(StatesGroup):
    in_menu = State()
    in_pair_task_menu = State()
    choosing_category = State()
    entering_text = State()
    choosing_energy = State()
    confirming_save = State()
    entering_pair_task_reflection_1 = State()
    entering_pair_task_reflection_2 = State()
