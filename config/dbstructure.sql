-- MySQL dump 10.13  Distrib 5.5.29, for Linux (x86_64)
--
-- Host: localhost    Database: wiki_production
-- ------------------------------------------------------
-- Server version	5.5.29

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `GWAS`
--

-- DROP TABLE IF EXISTS `GWAS`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `GWAS` (
  `pubmed_id` bigint(20) unsigned NOT NULL,
  `trait` varchar(255) NOT NULL,
  `gene_symbol` varchar(20) NOT NULL,
  PRIMARY KEY (`pubmed_id`,`trait`,`gene_symbol`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dbsources`
--

-- DROP TABLE IF EXISTS `dbsources`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `dbsources` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL DEFAULT '',
  `url` varchar(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `diseases`
--

-- DROP TABLE IF EXISTS `diseases`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `diseases` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` text NOT NULL,
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2133 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `drugs`
--

-- DROP TABLE IF EXISTS `drugs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `drugs` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL DEFAULT '',
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `status` enum('discontinued','OTC','prescription','tentative approval','approved-US','approved-Others') DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2centralities`
--

-- DROP TABLE IF EXISTS `entrez2centralities`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2centralities` (
  `entrez_id` int(10) unsigned NOT NULL,
  `deg` double NOT NULL DEFAULT '0',
  `close` double NOT NULL DEFAULT '0',
  `betw` double NOT NULL DEFAULT '0',
  `eigen` double NOT NULL DEFAULT '0',
  `ntwk_const` double NOT NULL DEFAULT '0',
  `cluster_coef` double NOT NULL DEFAULT '0',
  `pagerank` double NOT NULL DEFAULT '0',
  `hub` double NOT NULL DEFAULT '0',
  `authority` double NOT NULL DEFAULT '0',
  PRIMARY KEY (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2diseases`
--

-- DROP TABLE IF EXISTS `entrez2diseases`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2diseases` (
  `entrez_id` int(10) unsigned NOT NULL,
  `disease_id` int(10) unsigned NOT NULL,
  KEY `entrez_id` (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2diseases_count`
--

-- DROP TABLE IF EXISTS `entrez2diseases_count`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2diseases_count` (
  `entrez_id` int(10) unsigned NOT NULL,
  `count` int(10) unsigned NOT NULL,
  PRIMARY KEY (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2drugs`
--

-- DROP TABLE IF EXISTS `entrez2drugs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2drugs` (
  `entrez_id` int(10) unsigned NOT NULL,
  `drug_id` int(10) unsigned NOT NULL,
  KEY `entrez_id` (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `atc_codes`
--

-- DROP TABLE IF EXISTS `atc_codes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `atc_codes` (
  `drug_id` int(10) unsigned NOT NULL,
  `atc` varchar(8) NOT NULL,
  PRIMARY KEY (`drug_id`,`atc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2drugs_count`
--

-- DROP TABLE IF EXISTS `entrez2drugs_count`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2drugs_count` (
  `entrez_id` int(10) unsigned NOT NULL,
  `count` int(10) unsigned NOT NULL,
  PRIMARY KEY (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2enriched_go_terms`
--

-- DROP TABLE IF EXISTS `entrez2enriched_go_terms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2enriched_go_terms` (
  `entrez_id` int(10) unsigned NOT NULL,
  `go_id` varchar(32) NOT NULL,
  `pvalue` double NOT NULL DEFAULT '0',
  `pvalue_corr` double NOT NULL DEFAULT '0',
  KEY `entrez_id` (`entrez_id`,`pvalue_corr`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2ensembls`
--

-- DROP TABLE IF EXISTS `entrez2ensembls`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2ensembls` (
  `entrez_id` int(10) unsigned NOT NULL,
  `ensembl_id` varchar(255) NOT NULL,
  PRIMARY KEY (`entrez_id`,`ensembl_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2hprd`
--

-- DROP TABLE IF EXISTS `entrez2hprd`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2hprd` (
  `entrez_id` int(10) unsigned NOT NULL,
  `hprd_id` varchar(10) NOT NULL,
  PRIMARY KEY (`entrez_id`),
  KEY `index_hprd` (`hprd_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2pathways`
--

-- DROP TABLE IF EXISTS `entrez2pathways`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2pathways` (
  `entrez_id` int(10) unsigned NOT NULL,
  `pathway_id` int(10) unsigned NOT NULL,
  KEY `entrez_id` (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2pathways_count`
--

-- DROP TABLE IF EXISTS `entrez2pathways_count`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2pathways_count` (
  `entrez_id` int(10) unsigned NOT NULL,
  `count` int(10) unsigned NOT NULL,
  PRIMARY KEY (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2pdbs`
--

-- DROP TABLE IF EXISTS `entrez2pdbs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2pdbs` (
  `entrez_id` int(10) unsigned NOT NULL,
  `pdb_id` varchar(255) NOT NULL,
  PRIMARY KEY (`entrez_id`,`pdb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2tfidfs`
--

-- DROP TABLE IF EXISTS `entrez2tfidfs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2tfidfs` (
  `entrez_id` int(10) unsigned NOT NULL,
  `term` varchar(255) NOT NULL,
  `score` double NOT NULL,
  KEY `entrez_id` (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `entrez2uniprots`
--

-- DROP TABLE IF EXISTS `entrez2uniprots`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `entrez2uniprots` (
  `entrez_id` int(10) unsigned NOT NULL,
  `uniprot_id` varchar(255) NOT NULL,
  PRIMARY KEY (`entrez_id`,`uniprot_id`),
  KEY `index_uniprot` (`uniprot_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `genes`
--

-- DROP TABLE IF EXISTS `genes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `genes` (
  `id` int(10) unsigned NOT NULL,
  `symbol` varchar(255) NOT NULL DEFAULT '',
  `description` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `go_annotations`
--

-- DROP TABLE IF EXISTS `go_annotations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `go_annotations` (
  `entrez_id` int(10) unsigned NOT NULL,
  `go_id` varchar(32) NOT NULL,
  UNIQUE KEY `entrez_id_2` (`entrez_id`,`go_id`),
  KEY `entrez_id` (`entrez_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `go_terms`
--

-- DROP TABLE IF EXISTS `go_terms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `go_terms` (
  `id` varchar(32) NOT NULL,
  `name` varchar(255) NOT NULL DEFAULT '',
  `category` enum('Function','Component','Process') DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2centralities`
--

-- DROP TABLE IF EXISTS `interaction2centralities`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2centralities` (
  `interaction_id` int(10) unsigned NOT NULL,
  `brandes` double NOT NULL DEFAULT '0',
  PRIMARY KEY (`interaction_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2detections`
--

-- DROP TABLE IF EXISTS `interaction2detections`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2detections` (
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `detection_method` varchar(255) NOT NULL,
  KEY `dbsource_id` (`dbsource_id`,`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2externals`
--

-- DROP TABLE IF EXISTS `interaction2externals`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2externals` (
  `interaction_id` int(10) unsigned NOT NULL,
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  UNIQUE KEY `dbsource_id` (`dbsource_id`,`external_id`),
  KEY `interaction_id` (`interaction_id`,`dbsource_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2publications`
--

-- DROP TABLE IF EXISTS `interaction2publications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2publications` (
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `pmid` bigint(20) unsigned NOT NULL,
  KEY `dbsource_id` (`dbsource_id`,`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2scores`
--

-- DROP TABLE IF EXISTS `interaction2scores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2scores` (
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `score` double NOT NULL DEFAULT '0',
  KEY `dbsource_id` (`dbsource_id`,`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interaction2types`
--

-- DROP TABLE IF EXISTS `interaction2types`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interaction2types` (
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `interaction_type` varchar(255) NOT NULL,
  KEY `dbsource_id` (`dbsource_id`,`external_id`),
  KEY `index_interaction_type` (`interaction_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `interactions`
--

-- DROP TABLE IF EXISTS `interactions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `interactions` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `entrez_id1` int(10) unsigned NOT NULL,
  `entrez_id2` int(10) unsigned NOT NULL,
  `valid` tinyint(1) NOT NULL DEFAULT '1',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `entrez_id1_2` (`entrez_id1`,`entrez_id2`),
  KEY `entrez_id1` (`entrez_id1`,`entrez_id2`),
  KEY `index_valid` (`valid`)
) ENGINE=InnoDB AUTO_INCREMENT=359045 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `pageviews`
--

-- DROP TABLE IF EXISTS `pageviews`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `pageviews` (
  `id` int(10) unsigned NOT NULL,
  `pageview` int(10) unsigned DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `pathways`
--

-- DROP TABLE IF EXISTS `pathways`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `pathways` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL DEFAULT '',
  `dbsource_id` int(10) unsigned NOT NULL,
  `external_id` varchar(255) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=22089 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `psimi_ontologies`
--

-- DROP TABLE IF EXISTS `psimi_ontologies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `psimi_ontologies` (
  `id` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL DEFAULT '',
  `definition` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publication2authors`
--

-- DROP TABLE IF EXISTS `publication2authors`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `publication2authors` (
  `publication_id` bigint(20) unsigned NOT NULL,
  `author` varchar(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`publication_id`,`author`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publication2chemicals`
--

-- DROP TABLE IF EXISTS `publication2chemicals`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `publication2chemicals` (
  `publication_id` bigint(20) unsigned NOT NULL,
  `chemical` varchar(255) NOT NULL DEFAULT '',
  KEY `publication_id` (`publication_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publication2meshterms`
--

-- DROP TABLE IF EXISTS `publication2meshterms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `publication2meshterms` (
  `publication_id` bigint(20) unsigned NOT NULL,
  `meshterm` varchar(255) NOT NULL DEFAULT '',
  KEY `publication_id` (`publication_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publication2publications`
--

-- DROP TABLE IF EXISTS `publication2publications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `publication2publications` (
  `cited_id` bigint(20) unsigned NOT NULL,
  `citing_id` bigint(20) unsigned NOT NULL,
  PRIMARY KEY (`cited_id`,`citing_id`),
  KEY `cited_id` (`cited_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publications`
--

-- DROP TABLE IF EXISTS `publications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `publications` (
  `id` bigint(20) unsigned NOT NULL,
  `title` varchar(255) NOT NULL DEFAULT '',
  `citation` int(10) unsigned NOT NULL DEFAULT '0',
  `citation5` int(10) unsigned NOT NULL DEFAULT '0',
  `pubdate` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
  `journal` varchar(255) NOT NULL DEFAULT '',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `shortest_paths`
--

-- DROP TABLE IF EXISTS `shortest_paths`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `shortest_paths` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `entrez_id1` int(11) DEFAULT NULL,
  `entrez_id2` int(11) DEFAULT NULL,
  `path_len` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `entrez_id1` (`entrez_id1`),
  KEY `entrez_id2` (`entrez_id2`)
) ENGINE=InnoDB AUTO_INCREMENT=478956455 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `valid_direct_interacting_partners`
--

-- DROP TABLE IF EXISTS `valid_direct_interacting_partners`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `valid_direct_interacting_partners` (
  `entrez_id1` int(10) unsigned NOT NULL,
  `entrez_id2` int(10) unsigned NOT NULL,
  `known` tinyint(1) NOT NULL DEFAULT '0',
  `predicted` tinyint(1) NOT NULL DEFAULT '0',
  UNIQUE KEY `entrez_id1_2` (`entrez_id1`,`entrez_id2`),
  KEY `entrez_id1` (`entrez_id1`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `valid_direct_interactions`
--

-- DROP TABLE IF EXISTS `valid_direct_interactions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE IF NOT EXISTS `valid_direct_interactions` (
  `id` int(10) unsigned NOT NULL,
  `entrez_id1` int(10) unsigned NOT NULL,
  `entrez_id2` int(10) unsigned NOT NULL,
  `known` tinyint(1) NOT NULL DEFAULT '0',
  `predicted` tinyint(1) NOT NULL DEFAULT '0',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `entrez_id1_2` (`entrez_id1`,`entrez_id2`),
  KEY `entrez_id1` (`entrez_id1`,`entrez_id2`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2017-05-10 20:03:51
