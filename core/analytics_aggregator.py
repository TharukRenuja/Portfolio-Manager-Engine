"""
Analytics Aggregator - Pre-calculates analytics summaries to improve dashboard performance
"""
from datetime import datetime, timedelta
from firebase_admin import firestore
from core import database
from collections import defaultdict

def aggregate_analytics():
    """
    Aggregates analytics data incrementally to save Firestore quota.
    Updates: total views, monthly views, yearly views, top performing content.
    """
    if not database.db:
        return None
    
    try:
        # 1. Get current summary to find last watermark
        summary_ref = database.db.collection('analytics_summary').document('summary')
        summary_doc = summary_ref.get()
        current_summary = summary_doc.to_dict() if summary_doc.exists else {
            'total_views': 0, 'monthly_views': 0, 'yearly_views': 0,
            'top_blogs': [], 'top_projects': [], 'last_updated': datetime(2000, 1, 1)
        }
        
        last_updated = current_summary.get('last_updated', datetime(2000, 1, 1))
        # Handle string timestamps
        if isinstance(last_updated, str):
            try: last_updated = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            except: last_updated = datetime(2000, 1, 1)
        
        # 2. Get NEW analytics only
        from google.cloud.firestore import Query
        new_analytics = database.db.collection('analytics').where('timestamp', '>', last_updated).get()
        
        if not new_analytics:
            # Still update last_updated to current time to avoid reprocessing
            current_summary['last_updated'] = datetime.now()
            summary_ref.set(current_summary)
            return current_summary

        # 3. Process new data
        total_new = len(new_analytics)
        new_monthly = 0
        new_yearly = 0
        
        now = datetime.now()
        month_start = datetime(now.year, now.month, 1)
        year_start = datetime(now.year, 1, 1)

        # We'll use a transaction for the counters if we were truly distributed, 
        # but for this scale, reading/updating per run is fine for quota.
        # To keep Top 5 accurate without full scan, we maintain a 'counters' collection.
        batch = database.db.batch()
        
        for doc in new_analytics:
            data = doc.to_dict()
            timestamp = data.get('timestamp')
            item_type = data.get('item_type') or data.get('type') # Support both for transition
            item_id = data.get('item_id') or data.get('id')
            title = data.get('title', 'Unknown')

            if isinstance(timestamp, str):
                try: timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except: timestamp = None
            
            if timestamp and hasattr(timestamp, 'replace'):
                timestamp = timestamp.replace(tzinfo=None)
            
            if timestamp:
                if timestamp >= month_start: new_monthly += 1
                if timestamp >= year_start: new_yearly += 1
            
            # Update individual counters for Top lists
            if item_type in ['blog', 'project'] and item_id:
                counter_ref = database.db.collection('analytics_counters').document(f"{item_type}_{item_id}")
                # We can't really do "increment" easily in a batch without reading first, 
                # but Firestore has Increment.
                batch.set(counter_ref, {
                    'count': firestore.Increment(1),
                    'title': title,
                    'type': item_type,
                    'item_id': item_id
                }, merge=True)

        # 4. Finalize summary
        current_summary['total_views'] += total_new
        
        # Monthly/Yearly reset check
        current_period_month = month_start.strftime('%Y-%m')
        if current_summary.get('period_month') != current_period_month:
            current_summary['monthly_views'] = new_monthly
            current_summary['period_month'] = current_period_month
        else:
            current_summary['monthly_views'] += new_monthly
            
        if current_summary.get('period_year') != year_start.year:
            current_summary['yearly_views'] = new_yearly
            current_summary['period_year'] = year_start.year
        else:
            current_summary['yearly_views'] += new_yearly

        current_summary['last_updated'] = datetime.now()

        # 5. Refresh Top 5 lists
        # We read from the counters collection which is much smaller than the logs
        top_blogs_docs = database.db.collection('analytics_counters')\
            .where('type', '==', 'blog').order_by('count', direction=firestore.Query.DESCENDING).limit(5).get()
        current_summary['top_blogs'] = [{'id': d.get('item_id'), 'title': d.get('title'), 'views': d.get('count')} for d in top_blogs_docs]

        top_projects_docs = database.db.collection('analytics_counters')\
            .where('type', '==', 'project').order_by('count', direction=firestore.Query.DESCENDING).limit(5).get()
        current_summary['top_projects'] = [{'id': d.get('item_id'), 'title': d.get('title'), 'views': d.get('count')} for d in top_projects_docs]

        # Save all
        batch.commit()
        summary_ref.set(current_summary)
        
        return current_summary
        
    except Exception as e:
        print(f"Error aggregating analytics: {e}")
        return None

def get_analytics_summary():
    """
    Retrieves cached analytics summary or calculates if missing/stale.
    """
    if not database.db:
        return None
    
    try:
        # Try to get cached summary
        doc = database.db.collection('analytics_summary').document('summary').get()
        
        if doc.exists:
            summary = doc.to_dict()
            last_updated = summary.get('last_updated')
            
            # Handle string timestamps
            if isinstance(last_updated, str):
                try:
                    last_updated = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                except:
                    last_updated = None
            
            # Check if summary is fresh (less than 5 minutes old)
            if last_updated:
                if hasattr(last_updated, 'replace'):
                    last_updated = last_updated.replace(tzinfo=None)
                age = datetime.now() - last_updated
                if age < timedelta(minutes=5):
                    return summary
        
        # Summary is stale or missing, recalculate
        return aggregate_analytics()
        
    except Exception as e:
        print(f"Error getting analytics summary: {e}")
        return aggregate_analytics()
