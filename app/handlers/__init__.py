from app.handlers.observation import router as observation_router
from app.handlers.pair_test import router as pair_test_router
from app.handlers.start import router as start_router

__all__ = ["start_router", "pair_test_router", "observation_router"]
