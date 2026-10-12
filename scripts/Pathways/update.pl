#!/usr/bin/env perl

use strict;
use warnings;
use Term::ReadKey;
use DBI;
use Getopt::Long;

sub main {
    my $usage = "Usage: perl update.pl [Pathways File]\n";

    my($db, $user, $password);
    GetOptions ("user=s" => \$user,    # numeric
                "password=s"   => \$password,      # string
                "database=s"  => \$db);   # flag

    my $fname = $ARGV[0] or die $usage;
   
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

    eval {
        exec_main($dbh, $fname);
    };

    if ($@) {
        my $err = $@;
        $dbh->rollback();
        die $err;
    }
    else {
        $dbh->commit();
        print "Done with pathways\n";
        exit 0;
    }
}

sub exec_main {
    my ($dbh, $fname) = @_;
    open my $IN, '<', $fname or die "Failed to open $fname: $!\n";

    my $db_name = 'reactome';
    my $db_url = 'http://www.reactome.org/';
    my $sth_db = $dbh->prepare("SELECT id FROM dbsources WHERE name = ?");
    $sth_db->execute($db_name);
    my $dbsource_id = $sth_db->fetchrow;

    if (! $dbsource_id) {
        $sth_db = $dbh->prepare("INSERT into dbsources (name, url) values (?, ?)");
        $sth_db->execute($db_name, $db_url);
        $dbsource_id = $sth_db->{mysql_insertid};
    }

    my %has_seen_pathway = ();
    my $sth_pathways = $dbh->prepare(
        'INSERT IGNORE INTO pathways (name, dbsource_id, external_id) VALUE (?, ?, ?)'
    );  
    my $sth_uniprot = $dbh->prepare(
        "SELECT entrez_id FROM entrez2uniprots where uniprot_id = ?"
    );
    my $sth_entrez2pathways = $dbh->prepare(
        'INSERT IGNORE INTO entrez2pathways (entrez_id, pathway_id) VALUES '.
        '(?, (select id from pathways where dbsource_id = ? and external_id = ?))'
    );

    while (my $line = <$IN>) {
        chomp $line;
        my @terms = split(/\t/,$line);

        my $uniprot_id = $terms[0];
        my $react_id   = $terms[1];
        my $name       = $terms[3];##Changed by Madhavi

        if (! exists $has_seen_pathway{$react_id}) {
            $sth_pathways->execute($name, $dbsource_id, $react_id);
            $has_seen_pathway{$react_id} = 1;
        }

        $sth_uniprot->execute($uniprot_id);
        while(my $entrez_id = $sth_uniprot->fetchrow()) {
            $sth_entrez2pathways->execute($entrez_id, $dbsource_id, $react_id);
        }
    }

    close $IN;
}

main();
