import re


def is_last_sentence_a_question(text):
    """
    Determines if the last sentence of a given text is a finished question.
    """
    question_words = {"what", "where", "when", "why", "how", "who", "which", "whose"}

    # Split the text into sentences using punctuation as delimiters
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())

    if not sentences:
        return False

    # Get the last sentence
    last_sentence = sentences[-1].strip().lower()

    if not last_sentence:
        return False

    # Feature 1: Ends with a question mark
    if last_sentence.endswith("?"):
        return True

    # Feature 2: Starts with a question word
    if last_sentence.split()[0] in question_words:
        return True

    # Feature 3: Contains auxiliary verb inversion (e.g., "Do you", "Is she", etc.)
    if re.match(
        r"^(do|does|did|is|are|was|were|can|could|should|would|will|shall|have|has|had)\b",
        last_sentence,
    ):
        return True

    # Feature 4: Contains a tag question
    if re.search(
        r", (isn’t it|aren’t you|don’t you|didn’t he|won’t they|can’t we)\b", last_sentence
    ):
        return True

    return False
