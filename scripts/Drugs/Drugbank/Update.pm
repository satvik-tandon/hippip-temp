#!/usr/bin/perl

package Update;

use strict;
use DBI;
use Term::ReadKey;

sub new {
    my $class = shift;
    my %options = @_;

    my $self = {
        'verbose' => 0,
        'debug' => 0,
        'dbh' => undef,
        'usage' => "USAGE MESSAGE HERE",
        'progress' => 0,
        'prog_total' => 0,
        %options,
    };

    bless $self, $class;

    if(!$self->checkArgs()) {
        $self->usage();
        exit 1;
    }

    if(!$self->{dbh}) {
        $self->{dbh} = Update::connectDB();
    }

    return $self;
}

sub checkArgs {
    # SOME CODE TO OVERIDE HERE
    return 1;
}

sub log {
    my ($self,$message) = @_;
    if($self->{verbose}) {
        print STDERR $message;
    }
}

sub update {
    my $self = shift;
    eval {
        $self->exec_main();
    };
    if ($@) {
        print STDERR $@;
        print STDERR "Error encountered: rolling back changes.\n";
        $self->{dbh}->rollback();
        exit 1;
    }
    else {
        $self->{dbh}->commit();
    }
}

sub exec_main {
    print STDERR "USING DEFAULT MAIN!\n";
}

sub usage {
    my $self = shift;
    print $self->{usage}."\n";
}

sub connectDB {
    my $self = shift;

    ReadMode 1;
    print "dbname: ";
    my $db = <STDIN>;
    chomp $db;
    ReadMode 1;
    print "username: ";
    my $user = <STDIN>;
    chomp $user;
    ReadMode 2;
    print "password: ";
    my $password = <STDIN>;
    print "\n";
    chomp $password;
    ReadMode 1;

    my $dbh = DBI->connect("dbi:mysql:$db:localhost",$user,$password,
        {RaiseError => 1, AutoCommit => 0}) or die;

    if($self->{debug}) {
        $dbh->trace(2);
    }

    return $dbh;
}

sub logProgress {
    my $self = shift;
    $self->{progress}++;
    if($self->{progess} == 1 || int(100*$self->{progress}/$self->{prog_total}) > int(100*($self->{progress}-1)/$self->{prog_total})) {
        $self->log("Progress: ".int(100*$self->{progress}/$self->{prog_total})."%\r");
    }
}

1;
