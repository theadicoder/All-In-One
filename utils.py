from faker import Faker
from country_data import SUPPORTED_COUNTRIES

fake = Faker()

def generate_fake_address(country_code: str) -> dict:
    """Generate fake address for specific country"""
    if country_code not in SUPPORTED_COUNTRIES:
        return None
        
    fake.seed()  # Reset the seed
    
    try:
        # Configure locale based on country
        if country_code == 'US':
            return {
                "street": fake.street_address(),
                "city": fake.city(),
                "state": fake.state_abbr(),
                "zip": fake.zipcode(),
                "country": "United States"
            }
        else:
            return {
                "street": fake.street_address(),
                "city": fake.city(),
                "postal_code": fake.postcode(),
                "country": SUPPORTED_COUNTRIES[country_code]
            }
    except:
        return None
            return {
                "street": fake.street_address(),
                "city": fake.city(),
                "postal_code": fake.postcode(),
                "country": country_code
            }
    except:
        return None
