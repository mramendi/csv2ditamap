#!/usr/bin/env python3
"""
CSV to DITAMAP converter.
Parses a hierarchical CSV file where each row has one non-empty column,
and the position of that column indicates the hierarchical level.
"""

import csv
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class CSVEntry:
    """Represents a single entry from the CSV with its hierarchical level and text."""

    def __init__(self, level: int, text: str, line_number: int):
        self.level = level
        self.text = text
        self.line_number = line_number

    def __repr__(self):
        return f"CSVEntry(level={self.level}, text='{self.text}', line={self.line_number})"


def title_to_filename(title: str) -> str:
    """
    Convert a title to a valid DITA filename.

    Args:
        title: The title text to convert

    Returns:
        A valid filename ending with .dita

    Examples:
        "3.5.1.1. Managing cluster components" -> "managing_cluster_components.dita"
        "Introduction to OpenShift" -> "introduction_to_openshift.dita"
        "Chapter 1. Getting Started" -> "getting_started.dita"
        "CHAPTER 3.5.2 Installation" -> "installation.dita"
    """
    # Remove "chapter" (case-insensitive) at the start
    text = re.sub(r'^chapter\s*', '', title, flags=re.IGNORECASE)

    # Remove leading spaces
    text = text.lstrip()

    # Remove leading numbers with dots (e.g., "3.5.1.1." or "2.1.")
    text = re.sub(r'^\d+(\.\d+)*\.?\s*', '', text)

    # Strip and lowercase
    text = text.strip().lower()

    # Remove any remaining punctuation except spaces
    text = re.sub(r'[^\w\s]', '', text)

    # Replace multiple spaces with single underscore
    text = re.sub(r'\s+', '_', text)

    # Add .dita extension
    return f"{text}.dita"


def parse_csv(filepath: str) -> List[CSVEntry]:
    """
    Parse a CSV file into a list of CSVEntry objects.

    Args:
        filepath: Path to the CSV file

    Returns:
        List of CSVEntry objects with level and text information
    """
    entries = []

    with open(filepath, 'r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)

        # Skip the header row
        next(reader, None)

        for line_number, row in enumerate(reader, start=2):  # Start at 2 since we skipped header
            # Find all non-empty columns
            non_empty_columns = [(idx, col.strip()) for idx, col in enumerate(row) if col.strip()]

            # Skip lines with no non-empty columns
            if len(non_empty_columns) == 0:
                continue

            # Special case: if exactly columns 0 and 1 are filled, expand into two entries
            if (len(non_empty_columns) == 2 and
                non_empty_columns[0][0] == 0 and
                non_empty_columns[1][0] == 1):
                # Create two entries: level 0 first, then level 1
                entry0 = CSVEntry(level=0, text=non_empty_columns[0][1], line_number=line_number)
                entry1 = CSVEntry(level=1, text=non_empty_columns[1][1], line_number=line_number)
                entries.append(entry0)
                entries.append(entry1)
                continue

            # Warn if more than one non-empty column (other cases)
            if len(non_empty_columns) > 1:
                logger.warning(
                    f"Line {line_number}: Multiple non-empty columns found. "
                    f"Using first one. Columns: {non_empty_columns}"
                )

            # Get the first non-empty column
            level, text = non_empty_columns[0]

            # Create entry with level (number of empty columns before the non-empty one)
            entry = CSVEntry(level=level, text=text, line_number=line_number)
            entries.append(entry)

    return entries


def create_ditamap(map_id: str, map_title: str) -> ET.Element:
    """
    Create a DITAMAP structure with the root <map> element.

    Args:
        map_id: The ID attribute for the map element
        map_title: The title for the map

    Returns:
        ElementTree root element for the map
    """
    # Create root <map> element with id attribute
    map_root = ET.Element('map', attrib={'id': map_id})

    # Add <title> element
    title_elem = ET.SubElement(map_root, 'title')
    title_elem.text = map_title

    return map_root


def add_topicref(parent: ET.Element, href: str, topic_type: Optional[str] = None) -> ET.Element:
    """
    Add a topicref element to a parent element.

    Args:
        parent: The parent element to add the topicref to (typically <map> or another <topicref>)
        href: The href attribute (filename to reference)
        topic_type: Optional type attribute for the topicref (e.g., 'task', 'concept', 'reference')

    Returns:
        The created topicref element (allows for nesting by adding children to it)
    """
    attribs = {'href': href}
    if topic_type:
        attribs['type'] = topic_type

    topicref = ET.SubElement(parent, 'topicref', attrib=attribs)
    return topicref


def write_ditamap(map_root: ET.Element, output_file: str):
    """
    Write the DITAMAP to a file with proper DOCTYPE declaration and formatting.

    Args:
        map_root: The root map element
        output_file: Path to the output file
    """
    # Indent the XML for pretty printing
    ET.indent(map_root, space='  ')

    # We need to manually construct the output to include DOCTYPE
    with open(output_file, 'w', encoding='utf-8') as f:
        # Write XML declaration
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')

        # Write DOCTYPE declaration
        f.write('<!DOCTYPE map PUBLIC "-//OASIS//DTD DITA Map//EN" "technicalContent/dtd/map.dtd">\n')

        # Write the XML tree
        # Use ET.tostring to get the XML content
        xml_string = ET.tostring(map_root, encoding='unicode')
        f.write(xml_string)
        if not xml_string.endswith('\n'):
            f.write('\n')

    logger.info(f"DITAMAP written to {output_file}")


def process_level(parent: ET.Element, entries: List[CSVEntry], index: int) -> int:
    """Process the entry at the index and any entries of the same or subordinate levels, adding to the parent element
    returns the next index - either the level there is higher or it is past the end"""
    current_entry = entries[index]
    current_index = index
    min_level = current_entry.level
    parent_for_children = None
    while current_entry.level >= min_level:
        if current_entry.level == min_level:
            parent_for_children = add_topicref(parent, title_to_filename(current_entry.text))
            current_index += 1
        else:
            current_index = process_level(parent_for_children, entries, current_index)
        if current_index >= len(entries):
            break # the current index is past the end
        current_entry = entries[current_index]
    return current_index
            

def main():
    """Main function to demonstrate CSV parsing and DITAMAP creation."""
    import sys
    import os

    if len(sys.argv) < 3:
        print("Usage: csv2ditamap.py <csv_file> <output_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    logger.info(f"Parsing {csv_file}...")
    entries = parse_csv(csv_file)

    logger.info(f"Parsed {len(entries)} entries")

    # Display the first few entries as a demonstration
    print("\nFirst 10 entries:")
    for entry in entries[:10]:
        indent = "  " * entry.level
        print(f"{indent}[L{entry.level}] {entry.text}")

    if output_file:
        # Extract map ID from filename (without extension)
        map_id = os.path.splitext(os.path.basename(csv_file))[0]
        map_title = map_id  # Can be customized

        logger.info(f"\nCreating DITAMAP with id='{map_id}'...")
        map_root = create_ditamap(map_id, map_title)

        process_level(map_root, entries, 0)
        
        write_ditamap(map_root, output_file)
        print(f"\nDITAMAP structure created at: {output_file}")


if __name__ == "__main__":
    main()
