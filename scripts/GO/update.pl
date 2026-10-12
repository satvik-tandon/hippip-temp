#!/usr/bin/env perl

use strict;
use warnings;
use DBI;
use Term::ReadKey;
use Getopt::Long;

sub main {
    my $usage = "Usage: perl update.pl [gene2go]\n";

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
        print "Done with GO\n";
        exit 0;
    }
}

sub exec_main {
    my ($dbh, $fname) = @_;
    open my $IN, '<', $fname or die "Failed to open $fname: $!\n";

    print "Filling database. This may take several minutes...\n";

    my $garbage = <$IN>;
    my %seen_gene_ontology;
    my %seen_go_annotation;

    my $query1 = 'insert into go_terms (id, name, category) values (?, ?, ?)';
    my $query2 = 'insert into go_annotations (entrez_id, go_id) values (?, ?)';
    my $sth1 = $dbh->prepare($query1);
    my $sth2 = $dbh->prepare($query2);

    while(<$IN>){
        chomp;
        my @terms = split(/\t/,$_);
        next if $terms[0] ne '9606';

        my $eid      = $terms[1];
        my $go_id    = $terms[2];
        my $name     = $terms[5];
        my $category = $terms[7];

        if (! exists $seen_gene_ontology{$go_id}) {
            $sth1->execute($go_id, $name, $category);
            $seen_gene_ontology{$go_id} = 1;
        }

        if (! exists $seen_go_annotation{$eid}{$go_id}) {
            $sth2->execute($eid, $go_id);
            $seen_go_annotation{$eid}{$go_id} = 1;
        }
    }

    close $IN;
}

main();

