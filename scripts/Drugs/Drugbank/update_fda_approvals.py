#!/usr/bin/python3

from lxml import etree
import mysql.connector
from optparse import OptionParser
import sys

def extract_fda_approval_status_iter(xml_file):
    """
    Extract FDA approval status for drugs with 'primary' DrugBank ID and US-approved products.

    :param xml_file: Path to the XML file containing drug data
    :return: Generator yielding tuples (DrugBank ID, FDA Approval Status)
    """
    namespaces = {'ns': 'http://www.drugbank.ca'}

    # Use iterparse for efficient memory usage
    for event, elem in etree.iterparse(xml_file, events=("end",), tag="{http://www.drugbank.ca}drug"):
        # Extract the primary DrugBank ID
        primary_id_elem = elem.find("ns:drugbank-id[@primary='true']", namespaces)
        if primary_id_elem is not None:
            primary_id = primary_id_elem.text
        else:
            elem.clear()
            continue 

        # Check <products> for FDA approval
        name = elem.find("ns:name", namespaces).text
        products = elem.findall(".//ns:product", namespaces)
        fda_approved = any(
            product.find("ns:country", namespaces) is not None and
            product.find("ns:country", namespaces).text == "US" and
            product.find("ns:approved", namespaces) is not None and
            product.find("ns:approved", namespaces).text.lower() == "true"
            for product in products
        )
        other_approved = any(
            product.find("ns:country", namespaces) is not None and
            product.find("ns:country", namespaces).text != "US" and
            product.find("ns:approved", namespaces) is not None and
            product.find("ns:approved", namespaces).text.lower() == "true"
            for product in products
        )
        
        # Determine FDA approval status
        fda_status = "approved-US" if fda_approved else None
        other_approved_status = "approved-Others" if other_approved else None
        
        yield (primary_id, fda_status, other_approved_status)

        elem.clear()


if __name__ == '__main__':
    usage = "Usage: %prog [options] drugbank.xml"
    parser = OptionParser(usage=usage)
    parser.add_option("-d", "--database", dest="db", help="database to read from")
    parser.add_option("-u", "--user", dest="user", help="MySQL user")
    parser.add_option("-p", "--password", dest="passwd", help="MySQL password")
    parser.add_option("-f", "--file", dest="xml_file", help="Path to the DrugBank XML file")

    (options, args) = parser.parse_args()

    # Validate XML file path
    if not options.xml_file:
        parser.error("XML file path must be specified with -f or --file.")

    # Connect to MySQL database
    if options.db is None:
        options.db = input("MySQL dbname: ").strip()
    if options.user is None:
        options.user = input("MySQL username: ").strip()
    if options.passwd is None:
        import getpass
        options.passwd = getpass.getpass('MySQL password: ', sys.stderr)

    try:
        conn = mysql.connector.connect(
            host='localhost',
            db=options.db,
            user=options.user,
            passwd=options.passwd,
        )

        cursor = conn.cursor()

        query = """
                UPDATE drugs 
                SET status = %s
                WHERE external_id = %s
                """
        for drug in extract_fda_approval_status_iter(options.xml_file): 
            if drug[1] is not None:
                cursor.execute(query, (drug[1], drug[0]))
            elif drug[2] is not None:
                cursor.execute(query, (drug[2], drug[0]))
        
        conn.commit()
        print(f"{cursor.rowcount} rows updated successfully in the 'status' column.")
    
    except mysql.connector.Error as e:
        print(f"Error: {e}")
    
    finally:
        # Close SQL connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()
