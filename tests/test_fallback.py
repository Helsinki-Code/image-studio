import pytest

from app.services import ProviderResult, generate_or_edit_with_fallback


class FakeProvider:
    def __init__(self, name, *, fail=False):
        self.name = name
        self.fail = fail
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return ProviderResult(provider=self.name, image_path="/tmp/out.png", mime_type="image/png")

    def edit(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return ProviderResult(provider=self.name, image_path="/tmp/edit.png", mime_type="image/png")


def test_generation_falls_back_to_fal_when_openai_fails():
    openai = FakeProvider("openai", fail=True)
    fal = FakeProvider("fal")

    result = generate_or_edit_with_fallback(
        mode="generate",
        prompt="fashion portrait",
        providers=[openai, fal],
    )

    assert result.provider == "fal"
    assert openai.calls == 1
    assert fal.calls == 1


def test_edit_uses_first_successful_provider():
    openai = FakeProvider("openai")
    fal = FakeProvider("fal")

    result = generate_or_edit_with_fallback(
        mode="edit",
        prompt="change dress to black",
        image_path="/tmp/in.png",
        providers=[openai, fal],
    )

    assert result.provider == "openai"
    assert openai.calls == 1
    assert fal.calls == 0


def test_all_provider_failures_are_reported():
    with pytest.raises(RuntimeError) as exc:
        generate_or_edit_with_fallback(
            mode="generate",
            prompt="test",
            providers=[FakeProvider("openai", fail=True), FakeProvider("fal", fail=True)],
        )

    assert "openai failed" in str(exc.value)
    assert "fal failed" in str(exc.value)
