import random

COUNTRY_FORMATS = {
    'DE': ('DE', 22),  # Germany
    'FR': ('FR', 27),  # France
    'GB': ('GB', 22),  # United Kingdom
    'IT': ('IT', 27),  # Italy
    'ES': ('ES', 24),  # Spain
    'NL': ('NL', 18),  # Netherlands
    'BE': ('BE', 16),  # Belgium
    'US': ('US', 17),  # United States (unofficial)
}

def generate_iban(country_code: str) -> tuple[str, bool]:
    """Generate a simple IBAN-like number for demo purposes"""
    country_code = country_code.upper()
    if country_code not in COUNTRY_FORMATS:
        return "", False
    
    prefix, length = COUNTRY_FORMATS[country_code]
    
    # Generate random numbers for the body
    body_length = length - len(prefix)
    body = ''.join(random.choices('0123456789', k=body_length))
    
    # Format with spaces every 4 characters
    iban = f"{prefix}{body}"
    formatted_iban = ' '.join(iban[i:i+4] for i in range(0, len(iban), 4))
    
    return formatted_iban.strip(), True
