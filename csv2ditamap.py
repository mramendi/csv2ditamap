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
import os.path
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def title_to_basename(title: str) -> str:
    """
    Convert a title to a valid basename for a file.

    Args:
        title: The title text to convert

    Returns:
        A valid file basename

    Examples:
        "3.5.1.1. Managing cluster components" -> "managing_cluster_components"
        "Introduction to OpenShift" -> "introduction_to_openshift"
        "Chapter 1. Getting Started" -> "getting_started"
        "CHAPTER 3.5.2 Installation" -> "installation"
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

    return text



class Column:
    """Represents a non-empty column."""
    def __init__(self, idx: int, text: str):
        self.idx = idx
        self.text = text

    def __repr__(self):
        return f"Column {self.idx}: {self.text}"


class CSVEntry:
    """Represents a single entry from the CSV with its hierarchical level and text.
        Exception: categories get their own entries though can be on the same line"""

    def __init__(self, level: int, line_number: int, filename:str = None, is_job:bool = False, navtitle:str = ''):
        self.level = level
        self.line_number = line_number
        self.filename=filename
        self.is_job=is_job
        self.navtitle = navtitle

    def __repr__(self):
        return f"CSVEntry(level={self.level}, line={self.line_number}, filename={self.filename}, is_job={self.is_job}, navtitle={self.navtitle})"

# helper to read a column of a row safely
def get_column(row, index):
    if len(row) > index:
        return row[index].strip()
    return ''

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

        # Skip lines until we find the header line (first column says "Category")
        line_number = 0
        for row in reader:
            line_number += 1
            if row and row[0].strip().lower() == 'category':
                # Found the header line, skip it and start processing after
                break

        # Now process the rest of the rows
        for row in reader:
            shift_idx = 0
            line_number += 1

            # Find all non-empty columns
            non_empty_columns = [Column(idx, col.strip()) for idx, col in enumerate(row) if col.strip()]
            # TEMP
            #print(line_number, non_empty_columns)

            # if the first column is non-empty, create a category entry and delete from the list
            # A category never has a topic file name
            if (len(non_empty_columns) > 0) and (non_empty_columns[0].idx == 0):
                category_entry = CSVEntry(level=0, line_number=line_number, is_job=True, 
                                          filename=None, navtitle=non_empty_columns[0].text)
 
                entries.append(category_entry)
                del non_empty_columns[0]
#                shift_idx = 1


            # Skip lines with no non-empty columns (or just the "job" marker)
            if len(non_empty_columns) == 0:
                continue
            if (len (non_empty_columns) == 1) and (non_empty_columns[0].text.upper() in ["TRUE","FALSE"]):
                continue 

            entry_idx = non_empty_columns[0].idx
            # the text in non_empty_columns[0] gets discarded as the navtitle is a separate column
            entry_filename = None
            entry_is_job = False
            entry_navtitle = ""

            try:
                entry_filename = non_empty_columns[1].text.strip()
                if (entry_filename.lower().find(".dita") == -1) and (entry_filename.lower().find(".adoc") == -1):
                    logger.warning(f"Line {line_number}: filename does not seem to have the right extension? {entry_filename}")
                entry_filename, _ = os.path.splitext(entry_filename)
                

                entry_is_job = (non_empty_columns[2].text.strip().upper() == "TRUE")
                if not (non_empty_columns[2].text.strip().upper() in ["TRUE","FALSE"]):
                    logger.warning(f"Line {line_number}: is_job not TRUE nor FALSE? {non_empty_columns[2].text}")

                entry_navtitle = non_empty_columns[3].text
            except IndexError:
                logger.warning(f"Line {line_number} does not seem to have all fields")
                continue

            # temp
            #print(entry_filename)
            entry = CSVEntry(level=shift_idx+entry_idx, line_number=line_number, is_job=entry_is_job, filename=entry_filename, navtitle=entry_navtitle)
            entries.append(entry)


    # TEMP
    for entry in entries: print(entry)

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


def add_topicref(parent: ET.Element, href: str, topic_type: Optional[str] = None,
                 navtitle: str = '') -> ET.Element:
    """
    Add a topicref element to a parent element.

    Args:
        parent: The parent element to add the topicref to (typically <map> or another <topicref>)
        href: The href attribute (filename to reference)
        topic_type: Optional type attribute for the topicref (e.g., 'task', 'concept', 'reference')

    Returns:
        The created topicref element (allows for nesting by adding children to it)
    """
    if href is None: 
        href = "placeholder.dita"
    attribs = {'href': href}
    if topic_type:
        attribs['type'] = topic_type
    if navtitle:
        attribs['navtitle'] = topic_type

    topicref = ET.SubElement(parent, 'topicref', attrib=attribs)
    return topicref

def add_mapref(parent: ET.Element, href: str) -> ET.Element:
    """
    Add a mapref element to a parent element.

    Args:
        parent: The parent element to add the mapref to (typically <map> or a <topicref>)
        href: The href attribute (filename to reference)

    Returns:
        The created topicref element (allows for nesting by adding children to it)
    """
    attribs = {'href': href}

    topicref = ET.SubElement(parent, 'mapref', attrib=attribs)
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

def writeline(filename: str, line: str):
    with open(filename,"a") as f:
        f.write(line.rstrip()+"\n")


def process_level(parent: ET.Element, entries: List[CSVEntry], index: int, 
                  asciidoc_name: str, asciidoc_level: int) -> int:
    """Process the entry at the index and any entries of the same or subordinate levels, adding to the parent element
    returns the next index - either the level there is higher or it is past the end"""
    current_entry = entries[index]
    current_index = index
    min_level = current_entry.level
    parent_for_children = None
    asciidoc_name_for_children = asciidoc_name
    asciidoc_level_for_children = asciidoc_level + 1
    
    while current_entry.level >= min_level:
        # print(current_entry)
        if current_entry.level == min_level:
            if current_entry.is_job:
                # DO THE DITAMAP LOGIC HERE - temporarily skipped so all go to one ditamap
                asciidoc_name_for_children = "map_"+title_to_basename(current_entry.navtitle)+".adoc"
                writeline(asciidoc_name,f"include::{asciidoc_name_for_children}[leveloffset=+{asciidoc_level}]")
                writeline(asciidoc_name_for_children, f"= {current_entry.navtitle}")
                asciidoc_level_for_children = 1
            else:
                # as this is on the current level, UNDO the changes for writing children to submap
                asciidoc_name_for_children = asciidoc_name
                asciidoc_level_for_children = asciidoc_level + 1
                writeline(asciidoc_name,f"include::{current_entry.filename}.adoc[leveloffset=+{asciidoc_level}]")

            # temporarily do all ditamap here regardless of job
            if current_entry.filename:
                ditamap_filename = current_entry.filename+".dita"
            else:
                ditamap_filename = title_to_basename(current_entry.navtitle)+".dita"
            parent_for_children = add_topicref(parent, ditamap_filename)
            current_index += 1
        else:
            current_index = process_level(parent_for_children, entries, current_index,
                                          asciidoc_name_for_children, asciidoc_level_for_children)
        if current_index >= len(entries):
            break # the current index is past the end
        current_entry = entries[current_index]
    return current_index
            

def main():
    """Main function to demonstrate CSV parsing and DITAMAP creation."""

    if len(sys.argv) < 2:
        print("Usage: csv2ditamap.py <csv_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    base_name,_ = os.path.splitext(csv_file)
    output_file = base_name + ".ditamap"
    asciimap_file = "navigation_"+base_name+".adoc"

    logger.info(f"Parsing {csv_file}...")
    entries = parse_csv(csv_file)

    logger.info(f"Parsed {len(entries)} entries")
    #TEMP
    #sys.exit()


    if output_file:
        # Extract map ID from filename (without extension)
        map_id = os.path.splitext(os.path.basename(csv_file))[0]
        map_title = map_id  # Can be customized

        logger.info(f"\nCreating DITAMAP with id='{map_id}'...")
        map_root = create_ditamap(map_id, map_title)

        process_level(map_root, entries, 0, asciimap_file, 1)
        
        write_ditamap(map_root, output_file)
        print(f"\nDITAMAP structure created at: {output_file}")


if __name__ == "__main__":
    main()
