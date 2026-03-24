from aiogram.fsm.state import State, StatesGroup


class PairTest(StatesGroup):
    phase_1 = State()
    phase_2 = State()
    phase_3 = State()
    phase_4 = State()
    finished = State()


class PairTestStates(StatesGroup):
    waiting_for_mode = State()
    entering_code = State()

    waiting_phase1_score = State()
    waiting_phase1_word = State()
    phase1_waiting_other = State()

    phase2_answering = State()
    phase2_waiting_other = State()

    phase3_selecting_scenarios = State()
    phase3_waiting_selection_sync = State()
    phase3_answering = State()
    phase3_waiting_other = State()

    phase4_selecting_values = State()
    phase4_waiting_other = State()

    completed = State()
