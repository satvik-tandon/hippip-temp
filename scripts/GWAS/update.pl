#!/usr/bin/perl

use strict;
use DBI;
use IO::Handle;
use Term::ReadKey;
use File::Basename;
use Getopt::Long;

STDOUT->autoflush(1);

my $usage = "perl update.pl gwas-catalog-<version>-full.tsv\n"; 

my($db, $user, $password);
GetOptions ("user=s" => \$user,    # numeric
            "password=s"   => \$password,      # string
            "database=s"  => \$db);   # flag

my $fname = shift @ARGV or die $usage;

unless(-f $fname) {
    die "Unable to locate GWAS catalog file $fname\n";
}


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

open(IN,"<$fname") or die "Failed to open gwas catalog: $!\n";
<IN>;
my @data;
print "Reading GWAS catalog... ";
while(<IN>){
    chomp;
    my @fields = split("\t",$_);
    my $pubmed = $fields[1];
    my $trait = $fields[7];
    my $gene = $fields[13];
    if($gene !~ m/intergenic/i and $gene ne 'NR' and $trait) {
        my @genes = split(/,\s*/,$gene);
        foreach $gene(@genes) {
            chomp $gene;
            push(@data,[$pubmed, $trait, $gene]);
        }
    }
}
close IN;
print "Done\n";
print "Adding data to database... ";
foreach my $entry(@data) {
    my $sql =  "INSERT IGNORE INTO GWAS (pubmed_id,trait,gene_symbol) VALUES ($entry->[0], ".$dbh->quote($entry->[1]).", ".$dbh->quote($entry->[2]).")";
    my $sth = $dbh->prepare($sql);
    $sth->execute() or die "SQL Error: $DBI::errstr\n";
}
$dbh->commit();
print "Done\n"
