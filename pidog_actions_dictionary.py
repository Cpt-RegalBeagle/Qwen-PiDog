"""
pidog_actions_dictionary.py
Central action registry for PiDog. Two logical sections:

  PERSONALITY_ACTIONS  - Stationary expressions (head, tail, body pose).
                         Filtered from AI STT responses (text the AI says back).
                         The robot NEVER leaves its sitting position.
                         After each action the engine returns the dog to sit.

  MOVEMENT_ACTIONS     - Locomotion (trot, recall, etc.); consumed by pidog_command_engine (USER's STT).

Matching rules (applied by pidog_personality_engine and pidog_command_engine):
  - Case-insensitive substring scan.
  - "Yes" (sentence start) and "yes" (mid-sentence) both match "yes".
  - First match wins per message (MAX_ACTIONS_PER_MESSAGE).
"""

# ──────────────────────────────────────────────────────────────────
#  SECTION 1: PERSONALITY ACTIONS  (stationary only)
#  Filtered from: AI response text (STT received FROM the AI)
#  Constraint:  Robot stays in sitting position. Legs may move
#               (handshake, feet_shake) but no locomotion.
#  Post-action: Engine returns dog to sit automatically.
# ──────────────────────────────────────────────────────────────────
PERSONALITY_ACTIONS = {
    # --- Head / face ---
    "yes":                ("nod", []),
    "correct":            ("nod", []),
    "agreed":             ("nod", []),
    "affirmative":        ("nod", []),
    "indeed":             ("nod", []),
    "no":                 ("shake_head", []),
    "wrong":              ("shake_head", []),
    "incorrect":          ("shake_head", []),
    "disagree":           ("shake_head", []),
    "negative":           ("shake_head", []),
    "hmm":               ("tilting_head", []),
    "huh":               ("tilting_head", []),
    "confused":           ("fluster", []),
    "puzzled":            ("fluster", []),
    "curious":            ("tilting_head_left", []),
    "wondering":          ("tilting_head_right", []),
    "look up":            ("head_up_down", []),
    "look down":          ("head_up_down", []),

    # --- Tail / body emotion ---
    "happy":              ("wag_tail", []),
    "great":              ("wag_tail", []),
    "awesome":            ("wag_tail", []),
    "excited":            ("wag_tail", []),
    "good boy":           ("wag_tail", []),
    "love":               ("lick_hand", []),
    "sweet":              ("lick_hand", []),
    "congrats":           ("high_five", []),
    "well done":          ("high_five", []),
    "amazing":            ("high_five", []),
    "yay":                ("high_five", []),
    "surprise":           ("surprise", []),
    "wow":                ("surprise", []),
    "whoa":               ("surprise", []),
    "unexpected":         ("surprise", []),

    # --- Bark / alert (head only, no body movement) ---
    "bark":               ("head_bark", []),
    "woof":               ("head_bark", []),
    "alert":              ("head_bark", []),
    "watch out":          ("head_bark", []),
    "danger":             ("bark_harder", []),
    "stop":               ("bark_harder", []),
    "bad":                ("bark_harder", []),
    "howl":               ("howling", []),
    "moon":               ("howling", []),
    "lonely":             ("howling", []),

    # --- Sleep / rest (stationary poses) ---
    "sleep":              ("doze_off", []),
    "goodnight":          ("doze_off", []),
    "rest":               ("doze_off", []),
    "nap":                ("doze_off", []),
    "tired":              ("doze_off", []),
    "relax":              ("relax_neck", []),
    "calm":               ("relax_neck", []),
    "chill":              ("relax_neck", []),
    "meh":                ("nod_lethargy", []),
    "whatever":           ("nod_lethargy", []),

    # --- Body expression (stays in place) ---
    "dance":              ("twist_body", []),
    "spin":               ("twist_body", []),
    "turn":               ("twist_body", []),
    "sit":                ("half_sit", []),
    "stay":               ("half_sit", []),
    "wait":               ("waiting", []),
    "hold on":            ("waiting", []),
    "patient":            ("waiting", []),
    "stretch":            ("stretch", []),
    "morning":            ("stretch", []),
    "wake":               ("stretch", []),
    "exercise":           ("push_up", []),
    "strong":             ("push_up", []),
    "power":              ("push_up", []),
    "nervous":            ("feet_shake", []),
    "can't wait":         ("feet_shake", []),
    "give up":            ("lie_with_hands_out", []),
    "surrender":          ("lie_with_hands_out", []),
    "defeated":           ("lie_with_hands_out", []),

    # --- Greeting / social (legs move, no locomotion) ---
    "hello":              ("handshake", []),
    "hi":                 ("handshake", []),
    "greet":              ("handshake", []),
    "meet":               ("handshake", []),

    # --- Thinking ---
    "think":              ("think", []),
    "let me":             ("think", []),
    "consider":           ("think", []),
    "ponder":             ("think", []),

    # --- RGB mood (no physical movement) ---
    "party mode":         ("rgb_strip_set_mode", ["party", "rainbow"]),
    "red alert":          ("rgb_strip_set_mode", ["blink", "red"]),
    "calm mode":          ("rgb_strip_set_mode", ["breathe", "blue"]),
}

# SECTION 2: MOVEMENT ACTIONS (locomotion) — do not add to PERSONALITY_ACTIONS
MOVEMENT_ACTIONS = {
    "walk":               ("trot", []),
    "let's go":           ("trot", []),
    "move":               ("trot", []),
    "come here":          ("recall", []),
    "come":               ("recall", []),
}
