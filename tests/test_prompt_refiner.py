import pytest

from app.services import PromptRefiner


def test_refiner_preserves_user_prompt_and_does_not_add_false_synthetic_claim():
    refiner = PromptRefiner()

    refined = refiner.refine(
        "change her red dress to black",
        uploaded_people_are_synthetic=False,
    )

    assert "change her red dress to black" in refined.lower()
    assert "synthetic" not in refined.lower()
    assert "not a real person" not in refined.lower()
    assert "preserve identity" in refined.lower()


def test_refiner_allows_truthful_synthetic_context_when_user_confirms():
    refiner = PromptRefiner()

    refined = refiner.refine(
        "make the model wear a black dress",
        uploaded_people_are_synthetic=True,
    )

    assert "user confirms any depicted person is synthetic" in refined.lower()
    assert "make the model wear a black dress" in refined.lower()


def test_refiner_uses_low_moderation_for_generation_params():
    refiner = PromptRefiner()

    params = refiner.generation_params("a clean fashion portrait", size="1024x1024", quality="medium")

    assert params["model"] == "gpt-image-2"
    assert params["moderation"] == "low"
    assert params["size"] == "1024x1024"
    assert params["quality"] == "medium"
