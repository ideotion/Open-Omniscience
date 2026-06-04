"""
Helper Utilities

Provides helper functions for data parsing and processing.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
import logging

# Configure logging
logger = logging.getLogger(__name__)


def normalize_text(
    text: str,
    lower: bool = True,
    strip: bool = True,
    remove_accents: bool = True,
    remove_special: bool = False,
) -> str:
    """
    Normalize text for comparison and processing.
    
    Args:
        text: Text to normalize
        lower: Convert to lowercase
        strip: Strip whitespace
        remove_accents: Remove accents/diacritics
        remove_special: Remove special characters
        
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Convert to string if not already
    text = str(text)
    
    # Strip whitespace
    if strip:
        text = text.strip()
    
    # Remove accents/diacritics
    if remove_accents:
        text = unicodedata.normalize('NFKD', text)
        text = ''.join([c for c in text if not unicodedata.combining(c)])
    
    # Convert to lowercase
    if lower:
        text = text.lower()
    
    # Remove special characters
    if remove_special:
        text = re.sub(r'[^\w\s-]', '', text)
    
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    
    return text


def extract_numbers(
    text: str,
    as_float: bool = True,
    as_int: bool = False,
) -> List[Union[float, int]]:
    """
    Extract all numbers from text.
    
    Args:
        text: Text to extract numbers from
        as_float: Return numbers as float
        as_int: Return numbers as int (overrides as_float)
        
    Returns:
        List of extracted numbers
    """
    if not text:
        return []
    
    # Find all number patterns
    patterns = [
        r'-?\d+\.\d+',  # Negative/positive decimals
        r'-?\d+',  # Negative/positive integers
    ]
    
    numbers = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                if as_int:
                    numbers.append(int(match))
                elif as_float:
                    numbers.append(float(match))
                else:
                    numbers.append(float(match))
            except ValueError:
                continue
    
    return numbers


def extract_currency(
    text: str,
    symbols: Optional[List[str]] = None,
) -> List[str]:
    """
    Extract currency symbols from text.
    
    Args:
        text: Text to extract currency symbols from
        symbols: List of currency symbols to look for (None for common ones)
        
    Returns:
        List of found currency symbols
    """
    if not text:
        return []
    
    # Common currency symbols
    common_symbols = [
        '$', '€', '£', '¥', '₹', '₽', '₩', '₪', '₫', '₭',
        '₮', '₯', '₰', '₱', '₲', '₳', '₴', '₵', '₶', '₷',
        '₸', '₹', '₺', '₻', '₼', '₽', '₾', '₿',
    ]
    
    symbols_to_check = symbols or common_symbols
    
    found = []
    for symbol in symbols_to_check:
        if symbol in text:
            found.append(symbol)
    
    return found


def parse_price(
    text: str,
    currency: Optional[str] = None,
) -> Optional[float]:
    """
    Parse a price from text.
    
    Args:
        text: Text containing price
        currency: Optional currency symbol to remove
        
    Returns:
        Parsed price as float or None if parsing fails
    """
    if not text:
        return None
    
    # Remove currency symbols
    if currency:
        text = text.replace(currency, '')
    else:
        # Remove common currency symbols
        for sym in ['$', '€', '£', '¥', '₹']:
            text = text.replace(sym, '')
    
    # Remove commas (thousands separator)
    text = text.replace(',', '')
    
    # Remove any remaining non-numeric characters except decimal point and minus
    text = re.sub(r'[^\d.-]', '', text)
    
    # Handle cases like "1.234.567,89" (European format)
    if text.count('.') > 1 and text.count(',') == 1:
        # European format: 1.234.567,89 -> 1234567.89
        text = text.replace('.', '').replace(',', '.')
    elif text.count(',') > 1 and text.count('.') == 1:
        # Some other format
        text = text.replace(',', '')
    
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(
    text: str,
    formats: Optional[List[str]] = None,
) -> Optional[date]:
    """
    Parse a date from text.
    
    Args:
        text: Text containing date
        formats: List of date formats to try (None for common ones)
        
    Returns:
        Parsed date or None if parsing fails
    """
    if not text:
        return None
    
    # Common date formats
    common_formats = [
        '%Y-%m-%d',
        '%d/%m/%Y',
        '%m/%d/%Y',
        '%d-%m-%Y',
        '%m-%d-%Y',
        '%Y/%m/%d',
        '%b %d, %Y',  # Jan 15, 2024
        '%B %d, %Y',  # January 15, 2024
        '%d %b %Y',  # 15 Jan 2024
        '%d %B %Y',  # 15 January 2024
        '%Y%m%d',
        '%d.%m.%Y',
        '%m.%d.%Y',
    ]
    
    formats_to_try = formats or common_formats
    
    for fmt in formats_to_try:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    
    return None


def parse_production(
    text: str,
    unit: Optional[str] = None,
) -> Optional[float]:
    """
    Parse a production value from text.
    
    Args:
        text: Text containing production value
        unit: Optional unit to convert to tonnes
        
    Returns:
        Parsed production value in tonnes or None if parsing fails
    """
    if not text:
        return None
    
    # Extract the numeric value
    numbers = extract_numbers(text, as_float=True)
    if not numbers:
        return None
    
    value = numbers[0]  # Use the first number found
    
    # Convert to tonnes based on unit
    if unit:
        unit = unit.lower()
        if unit in ['kg', 'kilogram', 'kilograms']:
            value = value / 1000
        elif unit in ['g', 'gram', 'grams']:
            value = value / 1000000
        elif unit in ['ton', 'tonne', 'tonnes', 'tons']:
            pass  # Already in tonnes
        elif unit in ['lb', 'pound', 'pounds']:
            value = value * 0.000453592  # Convert pounds to tonnes
        elif unit in ['mt', 'metric ton', 'metric tons']:
            pass  # Already in tonnes
    
    return value


def parse_inventory(
    text: str,
    unit: Optional[str] = None,
) -> Optional[float]:
    """
    Parse an inventory value from text.
    
    Args:
        text: Text containing inventory value
        unit: Optional unit to convert to tonnes
        
    Returns:
        Parsed inventory value in tonnes or None if parsing fails
    """
    # Same as parse_production for now
    return parse_production(text, unit)


def format_price(
    price: float,
    currency: str = '$',
    decimals: int = 2,
    thousands_sep: str = ',',
    decimal_sep: str = '.',
) -> str:
    """
    Format a price for display.
    
    Args:
        price: Price to format
        currency: Currency symbol
        decimals: Number of decimal places
        thousands_sep: Thousands separator
        decimal_sep: Decimal separator
        
    Returns:
        Formatted price string
    """
    formatted = f"{price:,.{decimals}f}"
    formatted = formatted.replace(',', 'TEMP')
    formatted = formatted.replace('.', decimal_sep)
    formatted = formatted.replace('TEMP', thousands_sep)
    
    return f"{currency}{formatted}"


def format_date(
    date_obj: date,
    format_str: str = '%Y-%m-%d',
) -> str:
    """
    Format a date for display.
    
    Args:
        date_obj: Date to format
        format_str: Date format string
        
    Returns:
        Formatted date string
    """
    return date_obj.strftime(format_str)


def format_number(
    number: float,
    decimals: int = 2,
    thousands_sep: str = ',',
    decimal_sep: str = '.',
) -> str:
    """
    Format a number for display.
    
    Args:
        number: Number to format
        decimals: Number of decimal places
        thousands_sep: Thousands separator
        decimal_sep: Decimal separator
        
    Returns:
        Formatted number string
    """
    formatted = f"{number:,.{decimals}f}"
    formatted = formatted.replace(',', 'TEMP')
    formatted = formatted.replace('.', decimal_sep)
    formatted = formatted.replace('TEMP', thousands_sep)
    
    return formatted


def sanitize_filename(
    filename: str,
    replace_spaces: bool = True,
    max_length: int = 255,
) -> str:
    """
    Sanitize a string for use as a filename.
    
    Args:
        filename: String to sanitize
        replace_spaces: Replace spaces with underscores
        max_length: Maximum length of filename
        
    Returns:
        Sanitized filename
    """
    if not filename:
        return "unnamed"
    
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    
    # Replace spaces
    if replace_spaces:
        filename = filename.replace(' ', '_')
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Truncate to max length
    if len(filename) > max_length:
        filename = filename[:max_length]
    
    return filename


def generate_hash(
    data: Any,
    algorithm: str = 'md5',
) -> str:
    """
    Generate a hash for data.
    
    Args:
        data: Data to hash
        algorithm: Hash algorithm (md5, sha1, sha256, etc.)
        
    Returns:
        Hash string
    """
    import hashlib
    
    if isinstance(data, (dict, list, tuple)):
        data = str(data)
    elif not isinstance(data, (str, bytes)):
        data = str(data)
    
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    hash_obj = hashlib.new(algorithm, data)
    return hash_obj.hexdigest()


if __name__ == "__main__":
    # Test the helper functions
    print("Testing normalize_text...")
    text = "  Hello WORLD!  "
    normalized = normalize_text(text)
    print(f"Normalized: '{normalized}'")
    
    print("\nTesting extract_numbers...")
    text = "Price: $50,000.50 and 100 items"
    numbers = extract_numbers(text)
    print(f"Numbers: {numbers}")
    
    print("\nTesting extract_currency...")
    text = "Price: $50,000 and €45,000"
    currencies = extract_currency(text)
    print(f"Currencies: {currencies}")
    
    print("\nTesting parse_price...")
    prices = ["$50,000", "€45,000.50", "100", "1.234.567,89"]
    for price in prices:
        parsed = parse_price(price)
        print(f"'{price}' -> {parsed}")
    
    print("\nTesting parse_date...")
    dates = ["2024-01-15", "15/01/2024", "Jan 15, 2024"]
    for date_str in dates:
        parsed = parse_date(date_str)
        print(f"'{date_str}' -> {parsed}")
    
    print("\nTesting parse_production...")
    productions = ["100,000 tonnes", "50,000 kg", "1,000,000 grams"]
    for prod in productions:
        parsed = parse_production(prod)
        print(f"'{prod}' -> {parsed} tonnes")
    
    print("\nTesting format_price...")
    price = 50000.5
    formatted = format_price(price, currency='$')
    print(f"{price} -> {formatted}")
    
    print("\nDone!")
