#!/usr/bin/env perl

use strict;
use warnings;
use DBI;
use Term::ReadKey;
use Getopt::Long;

sub main {
    my $usage = "Usage: perl psi-mi_cv.pl [psi-mi25.obo]\n";
    
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
        print "Error encountered: rolling back changes.\n";
        $dbh->rollback();
        exit 1;
    }
    else {
        $dbh->commit();
        print "Done\n";
        exit 0;
    }
}

sub exec_main {
    my ($dbh, $fname) = @_;
    open my $IN, '<', $fname or die "Failed to open $fname: $!\n";

    print "Populating database tables...\n";


    my $term_query = $dbh->prepare("INSERT INTO psimi_ontologies (id, name, definition) VALUES (?, ?, ?)");
#    my $tree_query = $dbh->prepare("INSERT INTO psi_tree  (psi_id, is_a) VALUES (?, ?)");
    while (my $line = <$IN>) {
        next if $line !~ m/^\[Term\]/; # Skip to first entry

        my ($id,$name,$def,@is_a);

        do {
            $line = <$IN>;
            chomp $line;
            if($line =~ m/^id: (MI:\d{4})/){
                $id = $1;
            }
            elsif($line =~ m/^name: (.*)$/){
                $name = $1;
            }
            elsif($line =~ m/^is_a: (MI:\d{4})/){
                push(@is_a,$1);
            }
            elsif($line =~ m/^def: (.*)$/) {
                $def = $1;
            }
        } while($line);
        $term_query->execute($id, $name,$def);
#        foreach my $term(@is_a) {
 #           $tree_query->execute($id,$term);
 #       }
    }
    close $IN;
}

main();
