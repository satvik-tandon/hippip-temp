use strict;
use XML::Parser;
use DBI;
use IO::Handle;

# Queries
my $get_eid;
my $drug_insert_query;
my $target_insert_query;
my $atc_insert_query;

# Data
my $drugbank_id;
my $drug_name;
my @targets;
my @atcs;

# Progress data
my $total_drugs;
my $progress = 0;
my $location;

my $updater;

# Also, check that I'm using EXISTS in relevant SQL queries in other scripts.
sub main {
    STDOUT->autoflush(1);

    my $usage = <<USAGE;

Usage: perl drugbank.pl [DrugBank XML file]

Parses the contents of DrugBank into our local database.
USAGE

    $updater = myUpdate->new("usage" => $usage);
    $updater->update();

}

{
    package myUpdate;
    BEGIN {
        use Cwd 'abs_path';
        my ($dir) = abs_path($0) =~ /(.*)\/.*.pl/;
        unshift(@INC,$dir);
    }
    use base ("Update");
    use Getopt::Long;
    use Term::ReadKey;

    sub checkArgs {
        my $self = shift;

        my $verbose = 0;
        my($db, $user, $password);
        if(GetOptions('verbose' => \$verbose,
                      'user=s'  => \$user,
                      'password=s' => \$password,
                      'database=s' => \$db)  && @ARGV == 1) {
            $self->{fname} = $ARGV[0];
            $self->{verbose} = $verbose;

            if(!$db) {
                ReadMode 1;
                print "dbname: ";
                $db = <STDIN>;
                chomp $db;
            }
            if(!$user) {
                ReadMode 1;
                print "username: ";
                $user = <STDIN>;
                chomp $user;
            }
            if(!$password) {
                ReadMode 2;
                print "password: ";
                $password = <STDIN>;
                print "\n";
                chomp $password;
                ReadMode 1;
            }

            # my $dbh = DBI->connect("dbi:mysql:$db:localhost",$user,$password,
            #     {RaiseError => 1, AutoCommit => 0}) or die;

        # satvvik, after changing default socket path for MySQL,the new path has to be passed as argument to DBI 
            my $dbh = DBI->connect("dbi:mysql:$db;mysql_socket=/data/var/lib/mysql/mysql.sock",$user,$password,
                {RaiseError => 1, AutoCommit => 0}) or die;
            $self->{dbh} = $dbh;
            return 1;
        }
        return 0;
    }

    sub exec_main {
        my $self = shift;

        my $sth = $self->{dbh}->prepare("SELECT id FROM dbsources WHERE name = 'drugbank'");
        $sth->execute();
        my $ref = $sth->fetch();
        my $db_id;
        if($ref) {
            $db_id = $ref->[0];
        }
        else {
            $sth = $self->{dbh}->prepare("INSERT INTO dbsources (name, url) VALUES ('drugbank', 'http://www.drugbank.ca/')");
            $sth->execute();
            $db_id = $sth->{mysql_insertid}; 
        }

        $get_eid = $self->{dbh}->prepare("SELECT entrez_id FROM entrez2uniprots where uniprot_id = ?");
        $drug_insert_query = $self->{dbh}->prepare("INSERT INTO drugs (`name`, `dbsource_id`, `external_id`) VALUES (?, $db_id, ?)");
        $target_insert_query = $self->{dbh}->prepare("INSERT IGNORE INTO entrez2drugs (entrez_id, drug_id) VALUES (?, ?)");
        $atc_insert_query = $self->{dbh}->prepare("INSERT INTO atc_codes (drug_id, atc) VALUES(?, ?)");


        $total_drugs = `grep -c "<drug " $self->{fname}`;
        chomp $total_drugs;
        $self->{prog_total} = $total_drugs;

        my $parser = XML::Parser->new(Style => 'Subs',Handlers => {Char=>\&char_handler,End=>\&end_tag,Start=>\&start_tag});
        $parser->parsefile($self->{fname});
    }


    sub char_handler {
        my($expat,$content) = @_;
        chomp $content;
        if($expat->in_element("drugbank-id") && $expat->depth() == 3) {
            if($content =~ m/^DB\d+$/){
                $drugbank_id = $content;
            }
            # This condition is because of ridiculous strange formatting in the drugbank XML file that is beyond explanation
            elsif((!defined($drugbank_id) && $content =~ m/^D$/) || $expat->current_line() == $location) {
                $location = $expat->current_line();
                $drugbank_id .= $content;
            }

        }
        elsif($expat->in_element("name") && $expat->depth() == 3){
            $drug_name = $content;
        }
        elsif($expat->in_element("identifier") && $expat->within_element("target") && $content =~ m/[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}/){
            $get_eid->execute($content);
            while(my $ref = $get_eid->fetch()) {
                push(@targets,$ref->[0]);
            }
        }
    }
    sub end_tag {
        my($expat,$name) = @_;
        if($name eq "drug" && $expat->depth() == 1){
            if(defined($drugbank_id)) {
                $drug_insert_query->execute($drug_name,$drugbank_id);
                my $local_id = $drug_insert_query->{mysql_insertid};
                foreach my $target(@targets){
                    $target_insert_query->execute($target,$local_id);
                }
                foreach my $atc(@atcs){
                    $atc_insert_query->execute($local_id,$atc);
                }
            }
            @targets = ();
            @atcs = ();
            $drug_name = undef;
            $drugbank_id = undef;
            $progress++;
            $updater->logProgress();
        }
    }
    sub start_tag {
        my $expat = shift @_;
        my $name = shift @_;
        if($name eq "atc-code") {
            my %attrs = @_;
            push(@atcs, $attrs{"code"});
        }
    }
}

main();
