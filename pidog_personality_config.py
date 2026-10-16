"""
pidog_personality_config.py
User-editable dictionary mapping STT/AI response words & phrases to RPC actions.

Each entry: "trigger phrase" -> (rpc_method_name, [positional_args])
Matching is case-insensitive substring scan against the full response text.
Order matters: first match wins per scan pass (one action per message).
"""

# ──────────────────────────────────────────────
#  THE MAPPING  (edit freely)
# ──────────────────────────────────────────────
PERSONALITY_MAP = {
    # --- Head / face ---
    "yes":            ("nod", []),
    "correct":        ("nod", []),
    "agreed":         ("nod", []),
    "affirmative":    ("nod", []),
    "indeed":         ("nod", []),
    "no":             ("shake_head", []),
    "wrong":          ("shake_head", []),
    "incorrect":      ("shake_head", []),
    "disagree":       ("shake_head", []),
    "negative":       ("shake_head", []),
    "hmm":           ("tilting_head", []),
    "huh":           ("tilting_head", []),
    "confused":       ("fluster", []),
    "puzzled":        ("fluster", []),
    "curious":        ("tilting_head_left", []),
    "wondering":      ("tilting_head_right", []),
    "look up":        ("head_up_down", []),
    "look down":      ("head_up_down", []),

    # --- Tail / body emotion ---
    "happy":          ("wag_tail", []),
    "great":          ("wag_tail", []),
    "awesome":        ("wag_tail", []),
    "excited":        ("wag_tail", []),
    "good boy":       ("wag_tail", []),
    "love":           ("lick_hand", []),
    "sweet":          ("lick_hand", []),
    "congrats":       ("high_five", []),
    "well done":      ("high_five", []),
    "amazing":        ("high_five", []),
    "yay":            ("high_five", []),
    "surprise":       ("surprise", []),
    "wow":            ("surprise", []),
    "whoa":           ("surprise", []),
    "unexpected":     ("surprise", []),

    # --- Bark / alert ---
    "bark":           ("head_bark", []),
    "woof":           ("head_bark", []),
    "alert":          ("head_bark", []),
    "watch out":      ("head_bark", []),
    "danger":         ("bark_harder", []),
    "stop":           ("bark_harder", []),
    "bad":            ("bark_harder", []),
    "howl":           ("howling", []),
    "moon":           ("howling", []),
    "lonely":         ("howling", []),

    # --- Sleep / rest ---
    "sleep":          ("doze_off", []),
    "goodnight":      ("doze_off", []),
    "rest":           ("doze_off", []),
    "nap":            ("doze_off", []),
    "tired":          ("doze_off", []),
    "relax":          ("relax_neck", []),
    "calm":           ("relax_neck", []),
    "chill":          ("relax_neck", []),
    "meh":            ("nod_lethargy", []),
    "whatever":       ("nod_lethargy", []),

    # --- Movement / locomotion ---
    "walk":           ("trot", []),
    "let's go":       ("trot", []),
    "move":           ("trot", []),
    "dance":          ("twist_body", []),
    "spin":           ("twist_body", []),
    "turn":           ("twist_body", []),
    "sit":            ("half_sit", []),
    "stay":           ("half_sit", []),
    "wait":           ("waiting", []),
    "hold on":        ("waiting", []),
    "patient":        ("waiting", []),
    "come here":      ("recall", []),
    "come":           ("recall", []),
    "stretch":        ("stretch", []),
    "morning":        ("stretch", []),
    "wake":           ("stretch", []),
    "exercise":       ("push_up", []),
    "strong":         ("push_up", []),
    "power":          ("push_up", []),
    "nervous":        ("feet_shake", []),
    "can't wait":     ("feet_shake", []),
    "give up":        ("lie_with_hands_out", []),
    "surrender":      ("lie_with_hands_out", []),
    "defeated":       ("lie_with_hands_out", []),

    # --- Greeting / social ---
    "hello":          ("handshake", []),
    "hi":             ("handshake", []),
    "greet":          ("handshake", []),
    "meet":           ("handshake", []),

    # --- Thinking ---
    "think":          ("think", []),
    "let me":         ("think", []),
    "consider":       ("think", []),
    "ponder":         ("think", []),

    # --- RGB mood (positional args: mode, color) ---
    "party mode":     ("rgb_strip_set_mode", ["party", "rainbow"]),
    "red alert":      ("rgb_strip_set_mode", ["blink", "red"]),
    "calm mode":      ("rgb_strip_set_mode", ["breathe", "blue"]),
}

# ──────────────────────────────────────────────
#  TUNING KNOBS
# ──────────────────────────────────────────────
COOLDOWN_SECONDS = 2.0        # min gap between same-action firings
MAX_ACTIONS_PER_MESSAGE = 1   # only fire the first match per text blob
ENABLED = True                # master on/off switch
