# satvvik<This is the updated script for creating and updating the mySQL DB. There are some minor changes done to the script. The aim of creating this new script is:
# 1. Error Handling: I have added error handling at almost every step of the script so that it is easier to debug in case things go wrong.
# 2. Modularity: I have added modularity in the code by removing unnecessary variables and adding appropriate comments at every step. I have also implemented spinner during file downloading.
# 3. Readability: I have renamed a couple variables for better readability and code understanding.
# Overall, The logic used in the code is exactly the same other than the one I have mentioned below:
# (a). I added the fda approval script.
# (b). I have changed dbstructure.sql and commented out the part where tables were being dropped. (see next point about truncation)
# (c). I have added truncated function which truncates the tables since dbstructure is not deleting the existing tables anymore.>

#!/bin/bash

set -e
# set -x #satvvik<This is used to debug. Can be uncommented during debugging>
# set -o errexit #satvvik<This is same as set -e. Can be removed.>

# Usage documentation <satvik><I did a slight change in grammar. The overall instructions remain the same. I removed the "cat" function and made a it a variable instead named USAGE.>
USAGE="Usage: update [options]

Updates a HipPip database. The script requires a MySQL database name, username, and password as inputs.
The script runs verbosely by default, displaying progress on STDOUT, including error states.
Detailed error messages go to STDERR. It is recommended you use the following command to keep
a detailed log of update progress:

update 1> log 2> err.log

Options:
  -f, --force     Overwrite existing files when downloading source database files.
  -h, --help      Displays this usage text."

# Global variables
FORCE="FALSE"
RAWFILES="" #satvvik<I initialized BACKUP here. It is considered a good coding practice>
BACKUP="" #satvvik<I initialized RAWFILES here. It is considered a good coding practice>

# satvvik: Added variables for main and the cc email
EMAIL="madhavi@pitt.edu","sat362@pitt.edu"

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

# Truncate table function
# satvvik This is the new truncate function I implemented.
# This function truncates the table which also resets the auto-increment keys.
function truncate_table {
    local TABLE=$1
    echo "Truncating table: $TABLE..."
    mysql -u "$DB_USER" -p"$DB_PASS" -D "$TEMPLATE_DB" -e "TRUNCATE $TABLE;" 2>/dev/null || error "Failed to truncate table $TABLE"
    sleep 1s
    finish "Truncated $TABLE"
}

# Download file function

# satvvik: Changed the download function. 
# Added progress bar for download progress.
function download {
    local URL=$1
    local LOCAL_FILE="$RAWFILES/$(basename "$URL")"

    if [[ ! -f "$LOCAL_FILE" || $FORCE == "TRUE" ]]; then
        echo -ne "Downloading: $URL\n"
        
        # satvvik
	# Start the progress bar in the background.
        
        progress_bar &
        PROGRESS_PID=$!

        # Download the file
        if wget "$URL" -O "$LOCAL_FILE" -nv 2>&1; then 
            echo -e "\033[32mDownload Complete\033[0m"
        else
            #satvvik<If download fails, kill progress bar and handle the error.>
            kill "$PROGRESS_PID" 2>/dev/null
            wait "$PROGRESS_PID" 2>/dev/null
            error "Failed to download $URL"
        fi

        # satvvik
	# Ensure the progress bar process is terminated.>
        kill "$PROGRESS_PID" 2>/dev/null
        wait "$PROGRESS_PID" 2>/dev/null || true
    else
        echo "File already exists: $LOCAL_FILE. Use --force to overwrite."
    fi

    finish "Downloaded $LOCAL_FILE"
}


# satvvik<Progress bar animation function defined here. Note that this is newly added and was not there in the previous version of the script.>
function progress_bar {
    local SPINNER_CHARS='⠋⠙⠸⢰⢺⢸⠸'
    local SPINNER_COLOR="\033[34m"
    while true; do
        for (( i=0; i<${#SPINNER_CHARS}; i++ )); do
            echo -ne "${SPINNER_COLOR}\r${SPINNER_CHARS:$i:1} Downloading...\033[0m"
            sleep 0.1
        done
    done
}

# satvvik
# Validate MySQL credentials. 
# Changed the function name from check_access to check_mysql_accessl for better readability
# Added the error message in case DB is inaccessible>
function check_mysql_access {
    mysql -u "$DB_USER" -p"$DB_PASS" -D "$TEMPLATE_DB" -e ";" 2>/dev/null || error "Unable to access database $TEMPLATE_DB"
    mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e ";" 2>/dev/null || error "Unable to access database $PRODUCTION_DB"
}

# Parse command-line arguments
PARSED_OPTIONS=$(getopt -n "$0" -o fh --long "force,help" -- "$@")
eval set -- "$PARSED_OPTIONS"

while true; do
    case "$1" in
        -f|--force)
            FORCE="TRUE"
            shift
            ;;
        -h|--help)
            echo "$USAGE"
            exit 0
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

# satvvik
# Directly reading the name instead of printing the message and then read. 
read -p "MySQL Database: " PRODUCTION_DB
TEMPLATE_DB="tmp_$PRODUCTION_DB"  
read -p "MySQL Username: " DB_USER
read -s -p "MySQL Password: " DB_PASS

echo

# satvvik
# Calling function to validate mysql
check_mysql_access

# Prepare directories for RAWFILES and BACKUP.
RAWFILES="/data01/backup/rawfiles/$(/bin/date +%Y-%m-%d)"
BACKUP="/data01/backup/backups/"

if [ ! -d "$RAWFILES" ]; then
mkdir "$RAWFILES" -p
fi

if [ ! -d "$BACKUP" ]; then
mkdir "$BACKUP" -p
fi

BACKUP="$BACKUP/$(/bin/date +%Y-%m-%d)-$PRODUCTION_DB.sql"

ln -snf "$RAWFILES" /data01/backup/rawfiles/latest
#XXXMadhavi 
#Commented out the drugbank line because it seems to require login these days to download
#But copying an older version of drugbank file manually into the rawfiles folder so that it can still "update"
#or "insert" drugbank data into the database
#''' "http://www.drugbank.ca/system/downloads/current/drugbank.xml.zip" \ '''
#'''"http://viewvc.geneontology.org/viewvc/GO-SVN/trunk/gene-associations/gene_association.goa_human.gz" \'''
#'''"http://www.fda.gov/downloads/Drugs/InformationOnDrugs/UCM054599.zip" \'''
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
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene_info.gz"
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene2go.gz"
    "ftp://ftp.ncbi.nih.gov/gene/DATA/gene2ensembl.gz"
    "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/HUMAN_9606_idmapping.dat.gz"
    "http://www.reactome.org/download/current/UniProt2Reactome.txt"
    "http://thebiogrid.org/downloads/archives/Latest%20Release/BIOGRID-ALL-LATEST.mitab.zip"
    "http://geneontology.org/gene-associations/goa_human.gaf.gz"
    "https://www.ebi.ac.uk/gwas/api/search/downloads/full"
    "http://ontologies.berkeleybop.org/mi.obo"
    "https://ftp.ncbi.nih.gov/pub/HomoloGene/last-archive/homologene.data"
    "https://purl.obolibrary.org/obo/go/go-basic.obo" #satvvik added this link for go enrichment
)

# satvvik
# Changed to show file that's being downloaded. 
for URL in "${SOURCE_FILES[@]}"; do
    download "$URL"
    echo "DEBUG: Successfully downloaded $URL"
done

# Decompress files
for FILE in "$RAWFILES"/*.gz; do
    [[ -f "$FILE" ]] || continue
    gunzip -f "$FILE" || error "Failed to decompress $FILE"
done

for FILE in "$RAWFILES"/*.zip; do
    [[ -f "$FILE" ]] || continue
    unzip -o "$FILE" -d "$RAWFILES" || error "Failed to unzip $FILE"
done

# Rename biogrid file (has a version antecedent. 
# satvvik: Added error handling.
mv "$RAWFILES"/BIOGRID-ALL-*.mitab.txt "$RAWFILES/BIOGRID-ALL.mitab.txt" || error "Failed to rename BIOGRID file"
mv "$RAWFILES/full" "$RAWFILES/gwascatalog.txt" || error "Failed to rename GWAS catalog file"

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


# satvvik
# In the *dbstructure.sql*, I changed two things:
# 1. Previously, every table was being dropped and recreated. 
#    Creating tables again and again leads to continual increase of InnoDB size.
#    [In view of this, in *this* script, "truncate" has been added].
# 2. Added the line "IF NOT EXISTS" in the "CREATE TABLE" query 
#    since we are now not dropping the tables before creating them.

ERR=$(mysql -u "$DB_USER" --password="$DB_PASS" "$TEMPLATE_DB" < config/dbstructure.sql 2>&1)
if [[ $? -ne 0 ]]; then
    error "Failed to reset the database: $ERR"
fi
echo "Template database reset successfully."
finish


# satvvik
# In all the update scripts:
#    1) Removed the ERR variable as it was unnecessary. 
#    2) Truncating every table before running the script to populate it afresh.
#       This is because *drop table* has been removed from dbstructure.sql 
#       to prevent InnoDB from continually growing. 

# Genes: 
echo "Updating genes..."
truncate_table "genes" 
perl scripts/Genes/update.pl "$RAWFILES/gene_info" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update genes"
finish "Updated genes"

#GO terms and GO annotations
echo "Updating GO terms and GO annotations..."
truncate_table "go_annotations"
truncate_table "go_terms"
perl scripts/GO/update.pl "$RAWFILES/gene2go" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update GO terms and/or annotations"
finish "Updated GO terms and GO annotations"

#psimi_ontologies 
echo "Updating psimi ontology... "
truncate_table "psimi_ontologies"
perl scripts/psimi-ontology/psi-mi_cv.pl "$RAWFILES/mi.obo" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update psimi_ontologies"
finish "Updated psimi ontologies"

#entrez2hprd
echo "Updating HPRD IDs... "
truncate_table "entrez2hprd"
perl scripts/Cross/HPRD/update.pl "static/HPRD_ID_MAPPINGS.txt" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update entrez2hprd"
finish
finish "Updated entrez2hprd"

#entrez2ensembls
echo "Updating Ensembl IDs... "
truncate_table "entrez2ensembls"
perl scripts/Cross/Ensembl/update.pl "$RAWFILES/gene2ensembl" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS"  || error "Failed to update entrez2ensembls"
finish "Updated entrez2ensembls"

#entrez2uniprots
echo "Updating UniProt IDs... "
truncate_table "entrez2uniprots"
perl scripts/Cross/Uniprot/update.pl "$RAWFILES/HUMAN_9606_idmapping.dat" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update entrez2uniprots"
finish "Updated entrez2uniprots"

#dbsources, pathways and entrez2pathways
echo "Updating pathways... "
truncate_table "dbsources"
truncate_table "pathways"
truncate_table "entrez2pathways"
perl scripts/Pathways/update.pl "$RAWFILES/UniProt2Reactome.txt" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update pathways"
finish "Updated pathways"

#GWAS
echo "Updating GWASs... "
truncate_table "GWAS"
perl scripts/GWAS/update.pl "$RAWFILES/gwascatalog.txt" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update GWAS"
finish "Updated GWAS"

#entrez2pdbs
echo "Updating PDB IDs... "
truncate_table "entrez2pdbs"
scripts/pdb/update.py "$RAWFILES/HUMAN_9606_idmapping.dat" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update PDB IDs"
finish "Updated PDB IDs"

#diseases and entrez2diseases
echo "Updating diseases... "
truncate_table "diseases"
truncate_table "entrez2diseases"
scripts/kegg/insert_diseases.py static/diseases.kegg -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update diseases"
finish "Updated diseases"


# satvvik
# Dilemma: 
# We were not able to figure out the status section in drugs table since it had this enum set:
# enum('discontinued','OTC','prescription','tentative approval')
# We had no way to figure out from drugbank.xml that how to know the status of the drug. So we added 2 more enums- "approved-US" and "approved-others"
# Status column will have either of these values only. If neither of them is true, the value will remain NULL.>

#drugs, atc_codes and fda_approvals
echo "Updating drugs... "
truncate_table "drugs"
truncate_table "entrez2drugs"
truncate_table "atc_codes"
perl scripts/Drugs/Drugbank/drugbank.pl "$RAWFILES/../DRUGS/full_database.xml" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update drugs"
# satvvik<Added this update_fda_approval.py to update the fda approval status in the drugs table.
# Dilemma during populating this column is explained above.>
scripts/Drugs/Drugbank/update_fda_approvals.py -f "$RAWFILES/../DRUGS/full_database.xml" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update FDA status"
finish "Updated drugs and it's FDA status"

# satvvik<Truncating interaction2detections, interaction2externals, interaction2publications, interaction2scores, interaction2types and interactions tables before populating it>
echo "Updating interactions... "
truncate_table "interaction2detections"
truncate_table "interaction2externals"
truncate_table "interaction2publications"
truncate_table "interaction2scores"
truncate_table "interaction2types"
truncate_table "interactions"

#satvvik<I added appropriate error messages too.>
echo "Part I... Insert Interactions"
scripts/Interactions/update.py config/interaction_sources_pred.json -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update Interactions I"

echo "Part II... Insert valid_direct_interactions"
truncate_table "valid_direct_interactions"
truncate_table "interaction2centralities"
scripts/Interactions/insert_valid_direct_interactions.py -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update Interactions II"

echo "Part III... valid_direct_interacting_partners"
truncate_table "valid_direct_interacting_partners"
scripts/Interactions/insert_valid_direct_interacting_partners.py -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update Interactions III"
finish "Updated all the interactions"

#entrez2enriched_go_terms 
echo "Updating enriched GO terms... "
truncate_table "entrez2enriched_go_terms"
scripts/go-enrichment/enrichment_analysis.py "$RAWFILES/go-basic.obo" -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update Enriched GO terms"
finish "Updated enriched GO terms"


#publication2publications, publication2authors, 
#publication2chemicals, 
#publication2meshterms and publications 
echo -n "Updating publications... "
truncate_table "publication2publications"
truncate_table "publication2authors"
truncate_table "publication2chemicals"
truncate_table "publication2meshterms"
truncate_table "publications"
hours=$(/bin/date +%H)
echo $hours
if [ $hours -gt 03 -a $hours -lt 21 ]; then
    # echo -en "Stalling until 9pm\r" 
    sendmail "$EMAIL" <<EOF
Subject: Publication Update: Process Pending
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

This is to notify you that the publication process is scheduled but has not started yet. The system will begin the process at the designated time, and you will be informed when it begins.

Thank you for your patience.

Best regards,
Your Hippip Script
EOF

    current_epoch=$(date +%s)
    target_epoch=$(date -d '21:00' +%s)
    sleep_seconds=$(( $target_epoch - $current_epoch ))
    while [ $sleep_seconds -gt 0 ]; do
    
        hours_left=$(( sleep_seconds / 3600 ))
        minutes_left=$(( (sleep_seconds % 3600) / 60 ))
        seconds_left=$(( sleep_seconds % 60 ))

        echo -en "Time until publication: ${hours_left}h ${minutes_left}m ${seconds_left}s\r"
        sleep 1

        current_epoch=$(date +%s)
        sleep_seconds=$(( $target_epoch - $current_epoch ))
    done
    echo -n "Updating publications..."
    sleep 30
fi


START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
sendmail "$EMAIL" <<EOF
Subject: Publication Update: Process Started
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

This is to inform you that the publication process started at $START_TIME. The system is actively processing the updates, and the status will be communicated once the process completes.

Thank you for your attention.

Best regards,
Your Hippip Script
EOF

scripts/publication/update.py -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS" ||  error "Failed to update publications"
finish "Updated publications"
echo "Completed publications..."

# sendmail madhavi@pitt.edu < "$RAWFILES/EMAIL/email.txt"
#searchd --stop --config /data/1Projects/SPHINX/sphinx.conf
#indexer --config /data/1Projects/SPHINX/sphinx.conf --all
#searchd --config /data/1Projects/SPHINX/sphinx.conf

echo -n "Migrating template database to production database... "


echo -n "Backing up production database... "
ERR=$(mysqldump -u "$DB_USER" --password="$DB_PASS" "$PRODUCTION_DB" 2>/dev/null >$BACKUP) || error # satvvik<error in the script. Fixed it using GPT>
finish

# Migrate temporary database to production database
echo -n "Migrating template database to production database... "
ERR=$(mysqldump -u "$DB_USER" --password="$DB_PASS" "$TEMPLATE_DB" 2>/dev/null | mysql -u "$DB_USER" --password="$DB_PASS" "$PRODUCTION_DB") # satvvik<error in the script. Fixed it using GPT>

# sendmail sat362@pitt.edu < "$RAWFILES/EMAIL/email_2.txt"


sendmail "$EMAIL" <<EOF
Subject: Update: Data Push to $PRODUCTION_DB Completed
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

The data has been successfully pushed to the $PRODUCTION_DB database along with the publications. Additionally, the $TEMPLATE_DB database update has been completed successfully. 

The data push process for the shortest path calculations has now started.

Thank you for your attention.

Best regards,  
Your Hippip Script  
EOF

#shortest_paths
#Satvvik: Moved to the end of the script because it was taking too long to compute- 500k/hr approx (175 M in total)


echo "Updating shortest paths... "
truncate_table "shortest_paths"
scripts/shortest_paths/update_db.py -d "$TEMPLATE_DB" -u "$DB_USER" -p "$DB_PASS"  || error "Failed to update shortest path"
finish "Updated shortest path"

echo "Database update completed successfully!"

#satvvik: sendmail added here directly with content
sendmail "$EMAIL" <<EOF
Subject: Update: Shortest Path Data Pushed to $TEMPLATE_DB
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

The shortest path data has been successfully pushed to the $TEMPLATE_DB database. All processes for this operation have been completed.

Best regards,  
Your Hippip Script  
EOF


# REMINDER--- Satvvik:Finish and error message are not working and need to be fixed. Pending. ---REMINDER