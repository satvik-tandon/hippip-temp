#!/usr/bin/env perl

use strict;
use warnings;
use DBI;
use Term::ReadKey;
use Getopt::Long;

sub main {
    # Parse user arguments
    my $usage = "Usage: perl update.pl [gene_info]\n";
    
    my($db, $user, $password);
    GetOptions ("user=s" => \$user,    # numeric
                "password=s"   => \$password,      # string
                "database=s"  => \$db);   # flag

    my $fname = $ARGV[0] or die $usage;
   

    # Connect to MySQL database
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
    #     {RaiseError => 1, AutoCommit => 0}) or die "$!";
        
# satvvik, after changing default socket path for MySQL,the new path has to be passed as argument to DBI 
    my $dbh = DBI->connect("dbi:mysql:$db;mysql_socket=/data/var/lib/mysql/mysql.sock",$user,$password,
        {RaiseError => 1, AutoCommit => 0}) or die "$!";

    # Perform the update
    eval {
        exec_main($dbh, $fname);
    };

    # Confirm successful update or rollback changes
    if ($@) {
        my $err = $@;
        $dbh->rollback();
        die $err;
    }
    else {
        $dbh->commit();
        print "Done inserting genes\n";
        exit 0;
    }
}

sub exec_main {
    my ($dbh, $fname) = @_;
    open my $IN, '<', $fname or die "Failed to open $fname: $!\n";

    print "Filling database. This may take several minutes...\n";
    my $sth = $dbh->prepare("insert into genes (id, symbol, description) values (?, ?, ?) ");
    while (my $line = <$IN>) {
        chomp $line;
        my @terms = split(/\t/,$line);

        # Only use human genes (9606 is the human taxonomy id)
        my $tax_id = $terms[0];
        next if $tax_id ne '9606';

        # Parse the gene entry
        my $id          = $terms[1];
        my $symbol      = $terms[10];
        my $description = $terms[8];

        # Sanitize input
        #$id          =~ s/\'//g;
        #$symbol      =~ s/\'//g;
        #$description =~ s/\'//g;

        $sth->execute($id, $symbol, $description);
    }
    close $IN;
}

main();
