#!/usr/bin/env perl

use strict;
use warnings;
use Term::ReadKey;
use DBI;
use Getopt::Long;

sub main {
    my $usage = "Usage: perl update.pl [gene2ensembl]\n";

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
        print "Done inserting into entrez2ensembls\n";
        exit 0;
    }
}

sub exec_main {
    my ($dbh, $fname) = @_;
    open my $IN, '<', $fname or die "Failed to open $fname: $!\n";

    my $sth = $dbh->prepare("INSERT IGNORE INTO entrez2ensembls (entrez_id, ensembl_id)" .
                            "VALUES (?, ?)");

    my $header = <$IN>;
    while (my $line = <$IN>) {
        chomp $line;
        my @terms = split(/\t/, $line);
        next if $terms[0] ne "9606";
        my ($entrez_id, $ensembl_id) = ($terms[1], $terms[2]);
        $sth->execute($entrez_id, $ensembl_id);
    }
    close $IN;
}

main();
