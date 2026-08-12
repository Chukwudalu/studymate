from services.pipeline.prompts.generate_flashcards import FlashcardsOutput


def test_flashcards_output_accepts_normal_wrapped_list():
    output = FlashcardsOutput(flashcards=[{"front": "Q1", "back": "A1"}])
    assert len(output.flashcards) == 1


def test_flashcards_output_parses_json_encoded_string():
    # Regression guard: Claude sometimes returns the whole payload as a JSON-encoded string.
    output = FlashcardsOutput(flashcards='{"flashcards": [{"front": "Q1", "back": "A1"}]}')
    assert len(output.flashcards) == 1


def test_flashcards_output_wraps_single_unwrapped_dict():
    # Regression guard: Claude sometimes returns a single flashcard dict directly
    # instead of {"flashcards": [...]}, which previously raised a pydantic
    # "Field required" ValidationError.
    output = FlashcardsOutput(flashcards={"front": "Q1", "back": "A1"})
    assert len(output.flashcards) == 1
    assert output.flashcards[0].front == "Q1"


def test_flashcards_output_wraps_single_unwrapped_dict_as_json_string():
    output = FlashcardsOutput(flashcards='{"front": "Q1", "back": "A1"}')
    assert len(output.flashcards) == 1
