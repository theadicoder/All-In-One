import re
from typing import Tuple

def validate_card(card_number: str, exp_month: str, exp_year: str, cvv: str) -> Tuple[bool, str]:
    """
    Comprehensive card validation.
    Returns (is_valid, error_message)
    """
    # Card number validation
    if not re.match(r'^\d{15,16}$', card_number):
        return False, "Invalid card number length"

    # Basic Luhn check
    if not is_luhn_valid(card_number):
        return False, "Failed Luhn check"

    # Expiry validation
    try:
        month = int(exp_month)
        year = int(exp_year)
        if not (1 <= month <= 12):
            return False, "Invalid expiry month"
        if not (2024 <= year <= 2035):
            return False, "Invalid expiry year"
    except ValueError:
        return False, "Invalid expiry date format"

    # CVV validation
    if not re.match(r'^\d{3,4}$', cvv):
        return False, "Invalid CVV"

    return True, "Card details valid"

def is_luhn_valid(card_number: str) -> bool:
    """
    Implements the Luhn algorithm for card number validation.
    """
    def digits_of(n: str):
        return [int(d) for d in n]
    
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(str(d * 2)))
    return checksum % 10 == 0
