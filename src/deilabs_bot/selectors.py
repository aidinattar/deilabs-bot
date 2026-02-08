LAB_SELECTORS = [
    "select#lab",
    "select[name='lab']",
    "select",
]

ENTER_BUTTON_SELECTORS = [
    "button:has-text('Enter')",
    "input[type=submit][value='Enter']",
    "button.btn-primary",
    "button[type='submit']",
]

EXIT_BUTTON_SELECTORS = [
    "button:has-text('Exit from lab')",
    "input[type=submit][value^='Exit from lab']",
]
