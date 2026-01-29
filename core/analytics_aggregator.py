"""
Analytics Aggregator - Pre-calculates analytics summaries to improve dashboard performance
"""
from datetime import datetime, timedelta
from core import database
from collections import defaultdict

def aggregate_analytics():
    """
    Aggregates analytics data into summary for fast dashboard loading.
    Calculates: total views, monthly views, yearly views, top performing content.
    """
    if not database.db:
        return None
    
    try:
        # Fetch all analytics
        all_analytics = database.db.collection('analytics').get()
        
        # Initialize counters
        total_views = len(all_analytics)
        monthly_views = 0
        yearly_views = 0
        
        # Counters for top content
        blog_views = defaultdict(lambda: {'count': 0, 'title': ''})
        project_views = defaultdict(lambda: {'count': 0, 'title': ''})
        
        # Calculate time thresholds
        now = datetime.now()
        month_start = datetime(now.year, now.month, 1)
        year_start = datetime(now.year, 1, 1)
        
        # Process analytics
        for doc in all_analytics:
            data = doc.to_dict()
            timestamp = data.get('timestamp')
            item_type = data.get('item_type')
            item_id = data.get('item_id')
            title = data.get('title', 'Unknown')
            
            # Handle string timestamps from restored backups
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except:
                    timestamp = None
            
            # Remove timezone for comparison
            if timestamp and hasattr(timestamp, 'replace'):
                timestamp = timestamp.replace(tzinfo=None)
            
            # Count monthly/yearly
            if timestamp:
                if timestamp >= month_start:
                    monthly_views += 1
                if timestamp >= year_start:
                    yearly_views += 1
            
            # Count by item
            if item_type == 'blog' and item_id:
                blog_views[item_id]['count'] += 1
                blog_views[item_id]['title'] = title
            elif item_type == 'project' and item_id:
                project_views[item_id]['count'] += 1
                project_views[item_id]['title'] = title
        
        # Get top 5 performing content
        top_blogs = sorted(
            [{'id': k, 'title': v['title'], 'views': v['count']} for k, v in blog_views.items()],
            key=lambda x: x['views'],
            reverse=True
        )[:5]
        
        top_projects = sorted(
            [{'id': k, 'title': v['title'], 'views': v['count']} for k, v in project_views.items()],
            key=lambda x: x['views'],
            reverse=True
        )[:5]
        
        # Create summary document
        summary = {
            'total_views': total_views,
            'monthly_views': monthly_views,
            'yearly_views': yearly_views,
            'top_blogs': top_blogs,
            'top_projects': top_projects,
            'last_updated': datetime.now(),
            'period_month': month_start.strftime('%Y-%m'),
            'period_year': year_start.year
        }
        
        # Save to Firestore
        database.db.collection('analytics_summary').document('summary').set(summary)
        
        return summary
        
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
