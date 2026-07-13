-- index: idx_article_author
CREATE INDEX idx_article_author ON articles (author);

-- index: idx_article_canonical_url
CREATE INDEX idx_article_canonical_url ON articles (canonical_url);

-- index: idx_article_country
CREATE INDEX idx_article_country ON articles (country);

-- index: idx_article_country_language
CREATE INDEX idx_article_country_language ON articles (country, language);

-- index: idx_article_created_at
CREATE INDEX idx_article_created_at ON articles (created_at);

-- index: idx_article_hash
CREATE UNIQUE INDEX idx_article_hash ON articles (hash);

-- index: idx_article_keyword_article_id
CREATE INDEX idx_article_keyword_article_id ON article_keyword_association (article_id);

-- index: idx_article_keyword_keyword_id
CREATE INDEX idx_article_keyword_keyword_id ON article_keyword_association (keyword_id);

-- index: idx_article_language
CREATE INDEX idx_article_language ON articles (language);

-- index: idx_article_language_region
CREATE INDEX idx_article_language_region ON articles (language, region);

-- index: idx_article_link_article_id
CREATE INDEX idx_article_link_article_id ON article_links (article_id);

-- index: idx_article_link_classification
CREATE INDEX idx_article_link_classification ON article_links (classification);

-- index: idx_article_link_normalized_url
CREATE INDEX idx_article_link_normalized_url ON article_links (normalized_url);

-- index: idx_article_link_source_article_id
CREATE INDEX idx_article_link_source_article_id ON article_links (source_article_id);

-- index: idx_article_link_source_id
CREATE INDEX idx_article_link_source_id ON article_links (external_source_id);

-- index: idx_article_link_type
CREATE INDEX idx_article_link_type ON article_links (link_type);

-- index: idx_article_link_url
CREATE INDEX idx_article_link_url ON article_links (url);

-- index: idx_article_link_working
CREATE INDEX idx_article_link_working ON article_links (is_working);

-- index: idx_article_published_at
CREATE INDEX idx_article_published_at ON articles (published_at);

-- index: idx_article_region
CREATE INDEX idx_article_region ON articles (region);

-- index: idx_article_sentiment
CREATE INDEX idx_article_sentiment ON articles (sentiment_score);

-- index: idx_article_source_id
CREATE INDEX idx_article_source_id ON articles (source_id);

-- index: idx_article_source_published
CREATE INDEX idx_article_source_published ON articles (source_id, published_at);

-- index: idx_article_source_rel_anomaly
CREATE INDEX idx_article_source_rel_anomaly ON article_source_relationships (is_temporal_anomaly);

-- index: idx_article_source_rel_article_id
CREATE INDEX idx_article_source_rel_article_id ON article_source_relationships (article_id);

-- index: idx_article_source_rel_confidence
CREATE INDEX idx_article_source_rel_confidence ON article_source_relationships (confidence_score);

-- index: idx_article_source_rel_link_id
CREATE INDEX idx_article_source_rel_link_id ON article_source_relationships (link_id);

-- index: idx_article_source_rel_source_article_id
CREATE INDEX idx_article_source_rel_source_article_id ON article_source_relationships (source_article_id);

-- index: idx_article_source_rel_source_id
CREATE INDEX idx_article_source_rel_source_id ON article_source_relationships (source_id);

-- index: idx_article_source_rel_type
CREATE INDEX idx_article_source_rel_type ON article_source_relationships (relationship_type);

-- index: idx_article_word_count
CREATE INDEX idx_article_word_count ON articles (word_count);

-- index: idx_credibility_rule_active
CREATE INDEX idx_credibility_rule_active ON source_credibility_rules (is_active);

-- index: idx_credibility_rule_factor
CREATE INDEX idx_credibility_rule_factor ON source_credibility_rules (factor);

-- index: idx_credibility_rule_name
CREATE UNIQUE INDEX idx_credibility_rule_name ON source_credibility_rules (rule_name);

-- index: idx_external_source_country
CREATE INDEX idx_external_source_country ON external_sources (country);

-- index: idx_external_source_credibility
CREATE INDEX idx_external_source_credibility ON external_sources (credibility_score);

-- index: idx_external_source_domain
CREATE UNIQUE INDEX idx_external_source_domain ON external_sources (domain);

-- index: idx_external_source_name
CREATE INDEX idx_external_source_name ON external_sources (name);

-- index: idx_external_source_type
CREATE INDEX idx_external_source_type ON external_sources (source_type);

-- index: idx_external_source_verified
CREATE INDEX idx_external_source_verified ON external_sources (is_verified);

-- index: idx_keyword_category_id
CREATE INDEX idx_keyword_category_id ON keywords (category_id);

-- index: idx_keyword_frequency
CREATE INDEX idx_keyword_frequency ON keywords (frequency);

-- index: idx_keyword_is_entity
CREATE INDEX idx_keyword_is_entity ON keywords (is_entity);

-- index: idx_keyword_is_ngram
CREATE INDEX idx_keyword_is_ngram ON keywords (is_ngram);

-- index: idx_keyword_language
CREATE INDEX idx_keyword_language ON keywords (language);

-- index: idx_keyword_normalized_term
CREATE INDEX idx_keyword_normalized_term ON keywords (normalized_term);

-- index: idx_keyword_term
CREATE INDEX idx_keyword_term ON keywords (term);

-- index: idx_link_classification_active
CREATE INDEX idx_link_classification_active ON link_classification_rules (is_active);

-- index: idx_link_classification_priority
CREATE INDEX idx_link_classification_priority ON link_classification_rules (priority);

-- index: idx_link_classification_rule_name
CREATE UNIQUE INDEX idx_link_classification_rule_name ON link_classification_rules (rule_name);

-- index: idx_link_classification_type
CREATE INDEX idx_link_classification_type ON link_classification_rules (classification_type);

-- index: idx_metadata_country
CREATE INDEX idx_metadata_country ON source_metadata (country);

-- index: idx_metadata_language
CREATE INDEX idx_metadata_language ON source_metadata (language);

-- index: idx_metadata_robots_allowed
CREATE INDEX idx_metadata_robots_allowed ON source_metadata (robots_allowed);

-- index: idx_metadata_source_id
CREATE UNIQUE INDEX idx_metadata_source_id ON source_metadata (source_id);

-- index: idx_source_article_accessible
CREATE INDEX idx_source_article_accessible ON source_articles (is_accessible);

-- index: idx_source_article_hash
CREATE UNIQUE INDEX idx_source_article_hash ON source_articles (content_hash);

-- index: idx_source_article_published
CREATE INDEX idx_source_article_published ON source_articles (published_at);

-- index: idx_source_article_source_id
CREATE INDEX idx_source_article_source_id ON source_articles (source_id);

-- index: idx_source_article_url
CREATE UNIQUE INDEX idx_source_article_url ON source_articles (url);

-- index: idx_source_country
CREATE INDEX idx_source_country ON sources (country);

-- index: idx_source_domain
CREATE UNIQUE INDEX idx_source_domain ON sources (domain);

-- index: idx_source_enabled
CREATE INDEX idx_source_enabled ON sources (enabled);

-- index: idx_source_group_group_id
CREATE INDEX idx_source_group_group_id ON source_group_association (group_id);

-- index: idx_source_group_source_id
CREATE INDEX idx_source_group_source_id ON source_group_association (source_id);

-- index: idx_source_language
CREATE INDEX idx_source_language ON sources (language);

-- index: idx_source_priority
CREATE INDEX idx_source_priority ON sources (priority);

-- index: idx_source_region
CREATE INDEX idx_source_region ON sources (region);

-- index: idx_source_reliability
CREATE INDEX idx_source_reliability ON sources (reliability_score);

-- index: idx_source_type
CREATE INDEX idx_source_type ON sources (source_type);

-- index: ix_amd_article_id
CREATE INDEX ix_amd_article_id ON article_mentioned_dates (article_id);

-- index: ix_amd_mentioned_on
CREATE INDEX ix_amd_mentioned_on ON article_mentioned_dates (mentioned_on);

-- index: ix_amd_status
CREATE INDEX ix_amd_status ON article_mentioned_dates (status);

-- index: ix_article_analyses_article_id
CREATE INDEX ix_article_analyses_article_id ON article_analyses (article_id);

-- index: ix_commodity_prices_observed_on
CREATE INDEX ix_commodity_prices_observed_on ON commodity_prices (observed_on);

-- index: ix_commodity_prices_symbol
CREATE INDEX ix_commodity_prices_symbol ON commodity_prices (symbol);

-- index: ix_commodity_symbol_date
CREATE INDEX ix_commodity_symbol_date ON commodity_prices (symbol, observed_on);

-- index: ix_keyword_family_overrides_normalized_term
CREATE UNIQUE INDEX ix_keyword_family_overrides_normalized_term ON keyword_family_overrides (normalized_term);

-- index: ix_keyword_mentions_observed_on
CREATE INDEX ix_keyword_mentions_observed_on ON keyword_mentions (observed_on);

-- index: ix_keyword_supergroup_members_normalized_term
CREATE INDEX ix_keyword_supergroup_members_normalized_term ON keyword_supergroup_members (normalized_term);

-- index: ix_kwfam_family_key
CREATE INDEX ix_kwfam_family_key ON keyword_family_overrides (family_key);

-- index: ix_kwsg_member_unique
CREATE UNIQUE INDEX ix_kwsg_member_unique ON keyword_supergroup_members (supergroup_id, normalized_term);

-- index: ix_law_revisions_observed_at
CREATE INDEX ix_law_revisions_observed_at ON law_revisions (observed_at);

-- index: ix_lawdoc_category
CREATE INDEX ix_lawdoc_category ON law_documents (category);

-- index: ix_lawdoc_jurisdiction_url
CREATE UNIQUE INDEX ix_lawdoc_jurisdiction_url ON law_documents (jurisdiction, url);

-- index: ix_lawdoc_watched
CREATE INDEX ix_lawdoc_watched ON law_documents (watched);

-- index: ix_lawrev_doc_hash
CREATE UNIQUE INDEX ix_lawrev_doc_hash ON law_revisions (document_id, content_hash);

-- index: ix_lawrev_doc_time
CREATE INDEX ix_lawrev_doc_time ON law_revisions (document_id, observed_at);

-- index: ix_lawrev_flagged
CREATE INDEX ix_lawrev_flagged ON law_revisions (flagged);

-- index: ix_market_extraction_rules_source_id
CREATE INDEX ix_market_extraction_rules_source_id ON market_extraction_rules (source_id);

-- index: ix_market_extraction_rules_symbol
CREATE INDEX ix_market_extraction_rules_symbol ON market_extraction_rules (symbol);

-- index: ix_market_rule_category
CREATE INDEX ix_market_rule_category ON market_extraction_rules (category);

-- index: ix_market_rule_source
CREATE INDEX ix_market_rule_source ON market_extraction_rules (source_id);

-- index: ix_market_rule_symbol
CREATE INDEX ix_market_rule_symbol ON market_extraction_rules (symbol);

-- index: ix_mention_article
CREATE INDEX ix_mention_article ON keyword_mentions (article_id);

-- index: ix_mention_country
CREATE INDEX ix_mention_country ON keyword_mentions (country);

-- index: ix_mention_keyword_article
CREATE UNIQUE INDEX ix_mention_keyword_article ON keyword_mentions (keyword_id, article_id);

-- index: ix_mention_keyword_date
CREATE INDEX ix_mention_keyword_date ON keyword_mentions (keyword_id, observed_on);

-- index: ix_wiki_revisions_timestamp
CREATE INDEX ix_wiki_revisions_timestamp ON wiki_revisions (timestamp);

-- index: ix_wikipage_category
CREATE INDEX ix_wikipage_category ON wiki_pages (category);

-- index: ix_wikipage_watched
CREATE INDEX ix_wikipage_watched ON wiki_pages (watched);

-- index: ix_wikipage_wiki_title
CREATE UNIQUE INDEX ix_wikipage_wiki_title ON wiki_pages (wiki, title);

-- index: ix_wikirev_flagged
CREATE INDEX ix_wikirev_flagged ON wiki_revisions (flagged);

-- index: ix_wikirev_page_revid
CREATE UNIQUE INDEX ix_wikirev_page_revid ON wiki_revisions (page_id, revid);

-- index: ix_wikirev_page_time
CREATE INDEX ix_wikirev_page_time ON wiki_revisions (page_id, timestamp);

-- table: alembic_version
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- table: article_analyses
CREATE TABLE article_analyses (
	id INTEGER NOT NULL, 
	article_id INTEGER NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	result TEXT NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	prompt_version VARCHAR(50), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(article_id) REFERENCES articles (id) ON DELETE CASCADE
);

-- table: article_fts
CREATE VIRTUAL TABLE article_fts USING fts5(
        title, content,
        content='articles', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    );

-- table: article_fts_config
CREATE TABLE 'article_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;

-- table: article_fts_data
CREATE TABLE 'article_fts_data'(id INTEGER PRIMARY KEY, block BLOB);

-- table: article_fts_docsize
CREATE TABLE 'article_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);

-- table: article_fts_idx
CREATE TABLE 'article_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

-- table: article_keyword_association
CREATE TABLE article_keyword_association (
	article_id INTEGER NOT NULL, 
	keyword_id INTEGER NOT NULL, 
	frequency INTEGER, 
	position INTEGER, 
	relevance_score FLOAT, 
	created_at DATETIME, 
	PRIMARY KEY (article_id, keyword_id), 
	FOREIGN KEY(article_id) REFERENCES articles (id), 
	FOREIGN KEY(keyword_id) REFERENCES keywords (id)
);

-- table: article_keywords
CREATE TABLE article_keywords (
	article_id INTEGER NOT NULL, 
	keyword_id INTEGER NOT NULL, 
	frequency INTEGER, 
	first_position INTEGER, 
	last_position INTEGER, 
	relevance_score FLOAT, 
	created_at DATETIME, 
	PRIMARY KEY (article_id, keyword_id), 
	FOREIGN KEY(article_id) REFERENCES articles (id), 
	FOREIGN KEY(keyword_id) REFERENCES keywords (id)
);

-- table: article_links
CREATE TABLE article_links (
	id INTEGER NOT NULL, 
	article_id INTEGER NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	normalized_url VARCHAR(1000) NOT NULL, 
	link_text VARCHAR(500), 
	position INTEGER, 
	link_type VARCHAR(50), 
	classification VARCHAR(50), 
	external_source_id INTEGER, 
	source_article_id INTEGER, 
	is_followable BOOLEAN, 
	is_working BOOLEAN, 
	last_checked_at DATETIME, 
	redirect_url VARCHAR(1000), 
	http_status INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(article_id) REFERENCES articles (id), 
	FOREIGN KEY(external_source_id) REFERENCES external_sources (id), 
	FOREIGN KEY(source_article_id) REFERENCES source_articles (id)
);

-- table: article_mentioned_dates
CREATE TABLE article_mentioned_dates (
	id INTEGER NOT NULL, 
	article_id INTEGER NOT NULL, 
	mentioned_on DATE NOT NULL, 
	precision VARCHAR(10) NOT NULL, 
	snippet VARCHAR(300), 
	confidence FLOAT, 
	extractor VARCHAR(40), 
	status VARCHAR(12) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_amd_article_date UNIQUE (article_id, mentioned_on, precision), 
	FOREIGN KEY(article_id) REFERENCES articles (id) ON DELETE CASCADE
);

-- table: article_source_relationships
CREATE TABLE article_source_relationships (
	id INTEGER NOT NULL, 
	article_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	source_article_id INTEGER, 
	link_id INTEGER, 
	relationship_type VARCHAR(50), 
	time_delta_days FLOAT, 
	is_temporal_anomaly BOOLEAN, 
	confidence_score FLOAT, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(article_id) REFERENCES articles (id), 
	FOREIGN KEY(source_id) REFERENCES external_sources (id), 
	FOREIGN KEY(source_article_id) REFERENCES source_articles (id), 
	FOREIGN KEY(link_id) REFERENCES article_links (id)
);

-- table: articles
CREATE TABLE articles (
	id INTEGER NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	canonical_url VARCHAR(1000) NOT NULL, 
	source_id INTEGER NOT NULL, 
	title VARCHAR(500), 
	content TEXT NOT NULL, 
	compressed_content BLOB, 
	published_at DATETIME, 
	language VARCHAR(10), 
	hash VARCHAR(64) NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	region VARCHAR(50), 
	country VARCHAR(2), 
	author VARCHAR(255), 
	word_count INTEGER, 
	reading_time INTEGER, 
	sentiment_score FLOAT, 
	sentiment_label VARCHAR(20), 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	UNIQUE (hash)
);

-- table: commodity_prices
CREATE TABLE commodity_prices (
	id INTEGER NOT NULL, 
	symbol VARCHAR(32) NOT NULL, 
	market VARCHAR(100), 
	observed_on DATE NOT NULL, 
	price FLOAT NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	unit VARCHAR(16) NOT NULL, 
	source VARCHAR(255), 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

-- table: external_sources
CREATE TABLE external_sources (
	id INTEGER NOT NULL, 
	domain VARCHAR(255) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	url VARCHAR(500), 
	source_type VARCHAR(50), 
	credibility_score FLOAT, 
	political_bias FLOAT, 
	country VARCHAR(2), 
	language VARCHAR(10), 
	description TEXT, 
	founded_year INTEGER, 
	alexa_rank INTEGER, 
	social_media_followers INTEGER, 
	is_verified BOOLEAN, 
	last_verified_at DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (domain)
);

-- table: keyword_categories
CREATE TABLE keyword_categories (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	parent_id INTEGER, 
	color VARCHAR(20), 
	is_active BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	FOREIGN KEY(parent_id) REFERENCES keyword_categories (id)
);

-- table: keyword_family_overrides
CREATE TABLE keyword_family_overrides (
	id INTEGER NOT NULL, 
	normalized_term VARCHAR(255) NOT NULL, 
	family_key VARCHAR(255) NOT NULL, 
	canonical_label VARCHAR(255), 
	kind VARCHAR(40), 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

-- table: keyword_mentions
CREATE TABLE keyword_mentions (
	id INTEGER NOT NULL, 
	keyword_id INTEGER NOT NULL, 
	article_id INTEGER NOT NULL, 
	count INTEGER NOT NULL, 
	first_offset INTEGER, 
	observed_on DATE, 
	country VARCHAR(2), 
	city VARCHAR(120), 
	extractor VARCHAR(40), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(keyword_id) REFERENCES keywords (id) ON DELETE CASCADE, 
	FOREIGN KEY(article_id) REFERENCES articles (id) ON DELETE CASCADE
);

-- table: keyword_supergroup_members
CREATE TABLE keyword_supergroup_members (
	id INTEGER NOT NULL, 
	supergroup_id INTEGER NOT NULL, 
	normalized_term VARCHAR(255) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(supergroup_id) REFERENCES keyword_supergroups (id) ON DELETE CASCADE
);

-- table: keyword_supergroups
CREATE TABLE keyword_supergroups (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	color VARCHAR(16), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- table: keywords
CREATE TABLE keywords (
	id INTEGER NOT NULL, 
	term VARCHAR(255) NOT NULL, 
	normalized_term VARCHAR(255) NOT NULL, 
	language VARCHAR(10), 
	frequency INTEGER, 
	category_id INTEGER, 
	is_ngram BOOLEAN, 
	ngram_size INTEGER, 
	is_entity BOOLEAN, 
	entity_type VARCHAR(50), 
	relevance_score FLOAT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	extractor VARCHAR(40), 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES keyword_categories (id)
);

-- table: law_documents
CREATE TABLE law_documents (
	id INTEGER NOT NULL, 
	jurisdiction VARCHAR(8) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	official_url VARCHAR(1000), 
	category VARCHAR(40), 
	consolidated BOOLEAN, 
	watched BOOLEAN, 
	baseline_text BLOB, 
	baseline_hash VARCHAR(64), 
	last_hash VARCHAR(64), 
	last_size INTEGER, 
	last_checked_at DATETIME, 
	last_status VARCHAR(255), 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

-- table: law_revisions
CREATE TABLE law_revisions (
	id INTEGER NOT NULL, 
	document_id INTEGER NOT NULL, 
	observed_at DATETIME, 
	content_hash VARCHAR(64) NOT NULL, 
	size INTEGER, 
	delta_bytes INTEGER, 
	diff BLOB, 
	flagged BOOLEAN, 
	flag_reasons VARCHAR(500), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES law_documents (id) ON DELETE CASCADE
);

-- table: link_classification_rules
CREATE TABLE link_classification_rules (
	id INTEGER NOT NULL, 
	rule_name VARCHAR(100) NOT NULL, 
	pattern VARCHAR(500) NOT NULL, 
	classification_type VARCHAR(50) NOT NULL, 
	priority INTEGER, 
	is_active BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (rule_name)
);

-- table: market_extraction_rules
CREATE TABLE market_extraction_rules (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	category VARCHAR(20) NOT NULL, 
	symbol VARCHAR(32) NOT NULL, 
	label VARCHAR(120), 
	url VARCHAR(1000) NOT NULL, 
	selector VARCHAR(500) NOT NULL, 
	attribute VARCHAR(100), 
	value_regex VARCHAR(300), 
	currency VARCHAR(8) NOT NULL, 
	unit VARCHAR(16) NOT NULL, 
	market VARCHAR(100), 
	enabled BOOLEAN, 
	last_run_at DATETIME, 
	last_status VARCHAR(255), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE
);

-- table: source_articles
CREATE TABLE source_articles (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	title VARCHAR(500), 
	published_at DATETIME, 
	author VARCHAR(255), 
	summary TEXT, 
	content_hash VARCHAR(64), 
	word_count INTEGER, 
	sentiment_score FLOAT, 
	is_accessible BOOLEAN, 
	last_accessed_at DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES external_sources (id)
);

-- table: source_credibility_rules
CREATE TABLE source_credibility_rules (
	id INTEGER NOT NULL, 
	rule_name VARCHAR(100) NOT NULL, 
	factor VARCHAR(50) NOT NULL, 
	weight FLOAT, 
	min_value FLOAT, 
	max_value FLOAT, 
	is_inverse BOOLEAN, 
	is_active BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (rule_name)
);

-- table: source_group_association
CREATE TABLE source_group_association (
	source_id INTEGER NOT NULL, 
	group_id INTEGER NOT NULL, 
	added_at DATETIME, 
	PRIMARY KEY (source_id, group_id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	FOREIGN KEY(group_id) REFERENCES source_groups (id)
);

-- table: source_groups
CREATE TABLE source_groups (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	color VARCHAR(20), 
	is_tag_based BOOLEAN, 
	tag_pattern VARCHAR(500), 
	priority INTEGER, 
	rate_limit_ms INTEGER, 
	enabled BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- table: source_metadata
CREATE TABLE source_metadata (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	language VARCHAR(20), 
	country VARCHAR(2), 
	region VARCHAR(100), 
	city VARCHAR(100), 
	timezone VARCHAR(50), 
	robots_txt_url VARCHAR(500), 
	robots_allowed BOOLEAN, 
	crawl_delay INTEGER, 
	sitemap_url VARCHAR(500), 
	favicon_url VARCHAR(500), 
	logo_url VARCHAR(500), 
	contact_email VARCHAR(255), 
	social_twitter VARCHAR(255), 
	social_facebook VARCHAR(500), 
	social_linkedin VARCHAR(500), 
	alexa_rank INTEGER, 
	last_checked DATETIME, 
	notes TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (source_id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

-- table: sources
CREATE TABLE sources (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	domain VARCHAR(255) NOT NULL, 
	rss_url VARCHAR(500), 
	rate_limit_ms INTEGER, 
	enabled BOOLEAN, 
	priority INTEGER, 
	tags VARCHAR(500), 
	reliability_score INTEGER, 
	language VARCHAR(10), 
	region VARCHAR(50), 
	country VARCHAR(2), 
	source_type VARCHAR(50), 
	update_frequency INTEGER, 
	cacheability BOOLEAN, 
	PRIMARY KEY (id), 
	UNIQUE (domain)
);

-- table: wiki_pages
CREATE TABLE wiki_pages (
	id INTEGER NOT NULL, 
	wiki VARCHAR(16) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	pageid INTEGER, 
	watched BOOLEAN, 
	category VARCHAR(255), 
	baseline_revid INTEGER, 
	baseline_text BLOB, 
	last_revid INTEGER, 
	last_checked_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

-- table: wiki_revisions
CREATE TABLE wiki_revisions (
	id INTEGER NOT NULL, 
	page_id INTEGER NOT NULL, 
	revid INTEGER NOT NULL, 
	parent_revid INTEGER, 
	timestamp DATETIME, 
	editor VARCHAR(255), 
	editor_anon BOOLEAN, 
	comment TEXT, 
	size INTEGER, 
	delta_bytes INTEGER, 
	tags VARCHAR(500), 
	minor BOOLEAN, 
	bot BOOLEAN, 
	diff BLOB, 
	ores_damaging FLOAT, 
	ores_goodfaith FLOAT, 
	ores_provenance VARCHAR(80), 
	flagged BOOLEAN, 
	flag_reasons VARCHAR(500), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE
);

-- trigger: article_fts_ad
CREATE TRIGGER article_fts_ad AFTER DELETE ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
    END;

-- trigger: article_fts_ai
CREATE TRIGGER article_fts_ai AFTER INSERT ON articles BEGIN
        INSERT INTO article_fts(rowid, title, content)
        VALUES (new.id, new.title, new.content);
    END;

-- trigger: article_fts_au
CREATE TRIGGER article_fts_au AFTER UPDATE ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
        INSERT INTO article_fts(rowid, title, content)
        VALUES (new.id, new.title, new.content);
    END;

