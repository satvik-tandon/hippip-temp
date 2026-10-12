#!/bin/bash

set -e
set -o errexit

#read -r -d '' USAGE <<- EOF
USAGE=$(cat <<EOF
Usage: update [options]

Updates a HipPip database. The script takes a MySQL database, username, and password from STDIN.
The script runs verbosely by default, displaying progress on STDOUT, including error state.
Detailed error messages go to STDERR. It is recommended you use the following command to keep
a detailed log of update progress:

update 1> log 2> err.log

Options:
  -f, --force     When downloading source database files, overwrite existing files.
  -h, --help      Displays this text
EOF)

ERR=
FORCE="FALSE"
NEW="FALSE"

# Report an error and exit
function error {
    if [[ -t 1 ]]; then
        echo "[$(tput setaf 1)ERROR$(tput sgr0)]"
    else
        echo "[ERROR]"
    fi
    echo $ERR 1>&2
    exit 1
}

# Report that a task has compeleted
function finish {
    if [[ -t 1 ]]; then
        echo "[$(tput setaf 2)DONE$(tput sgr0)]"
    else 
        echo "[DONE]"
    fi
}

# Download a file
function download {
    LOCAL=$RAWFILES/$(basename $1)
    if [[ ! -e "$LOCAL" ]] || [ $FORCE = "TRUE" ]; then
        ERR=$(wget $1 -O "$LOCAL" -nv 2>&1)
    fi
}

# Check that credentials for a MySQL database are valid
function check_access {
    mysql -u "$USER" --password="$PASS" "$1" -e ";";
}

PARSED_OPTIONS=$(getopt -n "$0"  -o hi:o:kpx:v --long "force,help"  -- "$@")
eval set -- "$PARSED_OPTIONS"
 
while true;
do
  case "$1" in
 
    -f|--force)
      FORCE="TRUE"
      shift;;

    -h|--help)
      echo "$USAGE"
      exit 0
      shift;;

    --)
      shift
      break;;
  esac
done

# Get MySQL credentials
echo -n "MySQL Database: "
read PRODUCTION_DB
TEMPLATE_DB="tmp_$PRODUCTION_DB"
echo -n "MySQL Username: "
read USER
echo -n "MySQL Password: "
read -s PASS
echo

# Test credentials on relevant databases
check_access $PRODUCTION_DB || { echo "$(tput setaf 1)ERROR$(tput sgr0): Unable to log into $PRODUCTION_DB"; exit 1; }
check_access $TEMPLATE_DB || { echo "$(tput setaf 1)ERROR$(tput sgr0): Unable to log into $TEMPLATE_DB"; exit 1; }

# Check for directories of the current date
RAWFILES=/data01/backup/rawfiles/$(/bin/date +%Y-%m-%d)
BACKUP=/data01/backup/backups/

if [ ! -d "$RAWFILES" ]; then
mkdir "$RAWFILES" -p
fi
# The soft link is necessary for updating interactions
rm /data01/backup/rawfiles/latest
ln -s $RAWFILES /data01/backup/rawfiles/latest

if [ ! -d "$BACKUP" ]; then
mkdir "$BACKUP" -p
fi
BACKUP="$BACKUP/$(/bin/date +%Y-%m-%d)-$PRODUCTION_DB.sql"

# Download necessary files

#XXXMadhavi 
#Commented out the drugbank line because it seems to require login these days to download
#But copying an older version of drugbank file manually into the rawfiles folder so that it can still "update"
#or "insert" drugbank data into the database
#''' "http://www.drugbank.ca/system/downloads/current/drugbank.xml.zip" \ '''
#'''"http://viewvc.geneontology.org/viewvc/GO-SVN/trunk/gene-associations/gene_association.goa_human.gz" \'''
#'''"http://www.fda.gov/downloads/Drugs/InformationOnDrugs/UCM054599.zip" \
##SIMILARLY gene ontology file and PSIMI file are also not found at the given location. So for the time
##being, I am copying old ones from Dec 2018, manually.
##  "http://www.geneontology.org/ontology/obo_format_1_2/gene_ontology_ext.obo" \
##  "http://obo.cvs.sourceforge.net/viewvc/obo/obo/ontology/genomic-proteomic/protein/psi-mi.obo" \
##  "http://www.genome.gov/admin/gwascatalog.txt" \
##
## 2021-September-20 -- Notes by Madhavi
## http://viewvc.geneontology.org/viewvc/GO-SVN/trunk/gene-associations/goa_human.gaf.gz link has been replaced with the following link
## http://geneontology.org/gene-associations/goa_human.gaf.gz
## because the viewvc link was not working anymore

#XXXMadhavi
#Note new link to goa_human
SOURCE_FILES=(
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene_info.gz" \
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene2go.gz" \
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene2ensembl.gz" \
    "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/HUMAN_9606_idmapping.dat.gz" \
    "http://www.reactome.org/download/current/UniProt2Reactome.txt" \
    "http://thebiogrid.org/downloads/archives/Latest%20Release/BIOGRID-ALL-LATEST.mitab.zip" \
    "http://geneontology.org/gene-associations/goa_human.gaf.gz" \
    "https://www.ebi.ac.uk/gwas/api/search/downloads/full" \
    "http://ontologies.berkeleybop.org/mi.obo" \
    "ftp://ftp.ncbi.nih.gov/pub/HomoloGene/current/homologene.data" \
)
for i in `seq 0 $(expr ${#SOURCE_FILES[@]} - 1)`; do
    if [[ -t 1 ]]; then
       echo -en "Downloading files... $(expr $i + 1)/${#SOURCE_FILES[@]}\r"
    else
       echo -e "Downloading files... $(expr $i + 1)/${#SOURCE_FILES[@]}"
    fi
    download ${SOURCE_FILES[$i]} || {
       echo -en "Downloading files... "
       error
    }
 done
 echo -en "Downloading files... "
 finish
 ###
 # Decompress files
 echo -en "Decompressing files... "
 for FILE in "$RAWFILES/"*.gz; do
     ERR=$(gunzip -f -q "$FILE" ) || error
 done
 for FILE in "$RAWFILES/"*.zip; do
     echo $FILE
     if [ "$FORCE" = "TRUE" ]; then
        ERR=$(unzip -n -q "$FILE" -d "$RAWFILES/" ) || error
     else
        ERR=$(unzip -o -q "$FILE" -d "$RAWFILES/" ) || error
     fi
 done
 finish
 ###
 #### Rename biogrid file (has a version antecendent)
 mv "$RAWFILES"/BIOGRID-ALL-*.mitab.txt "$RAWFILES/BIOGRID-ALL.mitab.txt"
 mv "$RAWFILES/full" "$RAWFILES/gwascatalog.txt"
 ###
#### Create the homolog file
####echo "Generating homologous interactions file"
#@## #### You can define the organisms used for the homology file by editing config/taxonomies.txt
#@## #### Use the format of NCBI_TAX_ID\tOrganism Name
#@## #### Note that the organism name is not used by the script. It's just useful for remembereing what the IDs refer to
#@## ####perl scripts/Homology/homology.pl config/taxonomies.txt "$RAWFILES/homologene.data" "$RAWFILES/BIOGRID-ALL.mitab.txt" > "$RAWFILES/BIOGRID-HOMOLOGS.mitab.txt"
#@## ###
#@## #### Create files for including physical interactions
#@## ####echo "Generating physical interaction files"
#@## ####cp "$RAWFILES/BIOGRID-ALL.mitab.txt" "$RAWFILES/BIOGRID-ALL-PHYSICAL.mitab.txt"
#@## ####cp "$RAWFILES/BIOGRID-HOMOLOGS.mitab.txt" "$RAWFILES/BIOGRID-HOMOLOGS-PHYSICAL.miab.txt"
#@## ####sed -i 's/MI:0915/MI:0407/g' "$RAWFILES"/BIOGRID-*-PHYSICAL.mitab.txt
#@## ###
# Empty the temporary production database
echo -n "Reseting template database... "
ERR=$(mysql -u "$USER" --password="$PASS" "$TEMPLATE_DB" < config/dbstructure.sql 2>&1) || error
finish

### Begin filling the temporary template database
echo -n "Updating genes... "
ERR=$(perl scripts/Genes/update.pl "$RAWFILES/gene_info" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating gene ontology... "
ERR=$(perl scripts/GO/update.pl "$RAWFILES/gene2go" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating psimi ontology... "
#@## ERR=$(perl scripts/psimi-ontology/psi-mi_cv.pl "$RAWFILES/psi-mi.obo" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" 2>&1 > /dev/null) || error
#@## the new downoloaded file is called mi.obo. Not psi-mi.obo
ERR=$(perl scripts/psimi-ontology/psi-mi_cv.pl "$RAWFILES/mi.obo" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating HPRD IDs... "
ERR=$(perl scripts/Cross/HPRD/update.pl "static/HPRD_ID_MAPPINGS.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating Ensembl IDs... "
ERR=$(perl scripts/Cross/Ensembl/update.pl "$RAWFILES/gene2ensembl" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating UniProt IDs... "
ERR=$(perl scripts/Cross/Uniprot/update.pl "$RAWFILES/HUMAN_9606_idmapping.dat" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating pathways... "
ERR=$(perl scripts/Pathways/update.pl "$RAWFILES/UniProt2Reactome.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating GWASs... "
ERR=$(perl scripts/GWAS/update.pl "$RAWFILES/gwascatalog.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating PDB IDs... "
ERR=$(scripts/pdb/update.py "$RAWFILES/HUMAN_9606_idmapping.dat" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

echo -n "Updating diseases... "
ERR=$(scripts/kegg/insert_diseases.py static/diseases.kegg -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

####XXXMadhavi
####Commenting out this section to download Drugbank as it seems to require login to download files now. 
####Actually, hold on.. I am copying an earlier version manually and letting it insert that data
###
echo -n "Updating drugs... "
#@## ###
#@## ####Madhavi
#@## ####Changing the full_database.xml source to $RAWFILES/../DRUGS/full_database.xml"
#@## ####ERR=$(perl scripts/Drugs/Drugbank/drugbank.pl "$RAWFILES/full_database.xml" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" 2>&1 >> stdout.txt) || error
ERR=$(perl scripts/Drugs/Drugbank/drugbank.pl "$RAWFILES/../DRUGS/full_database.xml" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish

#@## #### Madhavi
#@## #### changing RAWFILES/Product.txt to RAWFILES/../DRUGS/Products.txt (notice Plural in new filename)
#echo -n "updating FDA approvals..."
#@## ####ERR=$(perl scripts/Drugs/Drugbank/drug_approval.pl "$RAWFILES/Product.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" 2>&1 >> stdout.txt) || error
#ERR=$(perl scripts/Drugs/Drugbank/drug_approval.pl "$RAWFILES/../DRUGS/Products.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
#finish


###echo -n "Updating drugs... "
###
###ERR=$(perl scripts/Drugs/Drugbank/drugbank.pl "$RAWFILES/full\ database.xml" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" 2>&1 >> stdout.txt) &&
###ERR=$(perl scripts/Drugs/Drugbank/drug_approval.pl "$RAWFILES/Product.txt" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" 2>&1 >> stdout.txt)
###|| {
###error
###}
###finish

echo -n "Updating interactions... "

echo -n "1... "
ERR=$(scripts/Interactions/update.py config/interaction_sources_pred.json -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
echo -n "2... "
ERR=$(scripts/Interactions/insert_valid_direct_interactions.py -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error 
echo -n "3... "
ERR=$(scripts/Interactions/insert_valid_direct_interacting_partners.py -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error 
finish

echo "Completed Insertion of Interactions..."
echo "Skipping Enriched GO Terms"
#@##echo -n "Updating enriched GO terms... "
#@###@##ERR=$(scripts/go-enrichment/enrichment_analysis.py "$RAWFILES/gene_ontology_ext.obo" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
#@##ERR=$(scripts/go-enrichment/enrichment_analysis.py "$RAWFILES/gene_ontology_ext.obo" -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
#@##finish

echo "Skipping Shortest Paths"
#@### Uncomment the following 3 lines to update the shortest paths table
#@##echo -n "Updating shortest paths... "
#@##ERR=$(scripts/shortest_paths/update_db.py -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
#@##finish

# Publications are special. We can only mass-query NCBI
# between the hours of 9pm and 5am
echo "Skipped Shortest Paths"
echo -n "Updating publications... "
hours=$(/bin/date +%H)
echo $hours
if [ $hours -gt 03 -a $hours -lt 21 ]; then
    echo -en "Stalling until 9pm\r" 
    current_epoch=$(date +%s)
    target_epoch=$(date -d '21:00' +%s)
    sleep_seconds=$(( $target_epoch - $current_epoch ))
    sleep $sleep_seconds
    echo -n "Updating publications...                    "
fi
ERR=$(scripts/publication/update.py -d "$TEMPLATE_DB" -u "$USER" -p "$PASS" ) || error
finish
echo "Completed publications..."
{
  echo To: madhavi@pitt.edu
  echo Subject: Completed job $0
  echo 
  echo Completed job $0
} | /usr/lib/sendmail -t


#@### Backup
echo -n "Backing up production database... "
ERR=$(mysqldump -u "$USER" --password="$PASS" "$PRODUCTION_DB" 2>&1 >$BACKUP) || error
finish

#@### Migrate temporary database to production database
echo -n "Migrating template database to production database... "
ERR=$(mysqldump -u "$USER" --password="$PASS" "$TEMPLATE_DB" 2>&1 | mysql -u "$USER" --password="$PASS" "$PRODUCTION_DB") || error
finish

echo "Update complete."
##sendmail madhavi@pitt.edu < "$RAWFILES/EMAIL/email.txt"
#searchd --stop --config /data/1Projects/SPHINX/sphinx.conf
#indexer --config /data/1Projects/SPHINX/sphinx.conf --all
#searchd --config /data/1Projects/SPHINX/sphinx.conf
