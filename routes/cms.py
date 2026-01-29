from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from slugify import slugify
from firebase_admin import firestore
from core import database
from core.shared import login_required, admin_required, trigger_rebuild

cms_bp = Blueprint('cms', __name__)

# --- Blog Management ---
@cms_bp.route('/blog')
@login_required
def blog_list():
    blogs = database.db.collection('blog').order_by('date', direction=firestore.Query.DESCENDING).get()
    blogs_data = {b.id: b.to_dict() for b in blogs}
    return render_template('blog/list.html', blogs=blogs_data)

@cms_bp.route('/blog/new', methods=['GET', 'POST'])
@admin_required
def blog_new():
    if request.method == 'POST':
        data = request.form.to_dict()
        custom_date = request.form.get('date')
        data['date'] = custom_date if custom_date else datetime.now().strftime('%Y-%m-%d')
        data['permalink'] = slugify(data.get('permalink')) if data.get('permalink') else slugify(data['title'])
        data['category'] = [category.strip() for category in request.form['category'].split(',')]
        data['views'] = 0
        data['status'] = data.get('status', 'draft')
        database.db.collection('blog').add(data)
        flash('Blog post created successfully!', 'success')
        return redirect(url_for('cms.blog_list'))
    return render_template('blog/edit.html', blog={}, blog_id=None, breadcrumbs=[{'label': 'Blog', 'url': url_for('cms.blog_list')}])

@cms_bp.route('/blog/edit/<blog_id>', methods=['GET', 'POST'])
@admin_required
def blog_edit(blog_id):
    blog_ref = database.db.collection('blog').document(blog_id)
    if request.method == 'POST':
        data = request.form.to_dict()
        data['permalink'] = slugify(data.get('permalink')) if data.get('permalink') else slugify(data['title'])
        data['category'] = [category.strip() for category in request.form['category'].split(',')]
        data['status'] = data.get('status', 'draft')
        blog_ref.update(data)
        trigger_rebuild()
        flash('Blog post updated successfully!', 'success')
        return redirect(url_for('cms.blog_list'))
    doc = blog_ref.get()
    if not doc.exists:
        flash('Blog post not found.', 'danger')
        return redirect(url_for('cms.blog_list'))
    return render_template('blog/edit.html', blog=doc.to_dict(), blog_id=blog_id, breadcrumbs=[{'label': 'Blog', 'url': url_for('cms.blog_list')}])

@cms_bp.route('/blog/delete', methods=['POST'])
@admin_required
def blog_delete():
    blog_id = request.form.get('blog_id')
    if blog_id: database.db.collection('blog').document(blog_id).delete()
    flash('Blog post deleted.', 'warning')
    return redirect(url_for('cms.blog_list'))

# --- Projects Management ---
@cms_bp.route('/projects')
@login_required
def project_list():
    projects = database.db.collection('projects').order_by('date', direction=firestore.Query.DESCENDING).get()
    projects_data = {p.id: p.to_dict() for p in projects}
    for project_id, project in projects_data.items():
        if isinstance(project.get('category'), str):
            project['category'] = project['category'].split(', ')
    return render_template('projects/list.html', projects=projects_data)

@cms_bp.route('/projects/new', methods=['GET', 'POST'])
@admin_required
def project_new():
    if request.method == 'POST':
        data = request.form.to_dict()
        custom_date = request.form.get('date')
        data['date'] = custom_date if custom_date else datetime.now().strftime('%Y-%m-%d')
        data['permalink'] = slugify(data.get('permalink')) if data.get('permalink') else slugify(data['title'])
        if 'category' in data and isinstance(data['category'], str):
            data['category'] = [category.strip() for category in data['category'].split(',')]
        data['featured'] = 'featured' in data
        database.db.collection('projects').add(data)
        trigger_rebuild()
        flash('Project created successfully!', 'success')
        return redirect(url_for('cms.project_list'))
    return render_template('projects/edit.html', project={}, project_id=None, breadcrumbs=[{'label': 'Projects', 'url': url_for('cms.project_list')}])

@cms_bp.route('/projects/edit/<project_id>', methods=['GET', 'POST'])
@admin_required
def project_edit(project_id):
    project_ref = database.db.collection('projects').document(project_id)
    if request.method == 'POST':
        data = request.form.to_dict()
        data['permalink'] = slugify(data.get('permalink')) if data.get('permalink') else slugify(data['title'])
        if 'category' in data and isinstance(data['category'], str):
            data['category'] = [category.strip() for category in data['category'].split(',')]
        data['featured'] = 'featured' in data
        project_ref.update(data)
        trigger_rebuild()
        flash('Project updated successfully!', 'success')
        return redirect(url_for('cms.project_list'))
    doc = project_ref.get()
    if not doc.exists:
        flash('Project not found.', 'danger')
        return redirect(url_for('cms.project_list'))
    return render_template('projects/edit.html', project=doc.to_dict(), project_id=project_id, breadcrumbs=[{'label': 'Projects', 'url': url_for('cms.project_list')}])

@cms_bp.route('/projects/delete', methods=['POST'])
@admin_required
def project_delete():
    project_id = request.form.get('project_id')
    if project_id: database.db.collection('projects').document(project_id).delete()
    flash('Project deleted.', 'warning')
    return redirect(url_for('cms.project_list'))

# --- Career Management ---
@cms_bp.route('/career')
@login_required
def career_list():
    careers = database.db.collection('career').get()
    careers_data = {c.id: c.to_dict() for c in careers}
    return render_template('career.html', career=careers_data)

@cms_bp.route('/career/add', methods=['POST'])
@admin_required
def career_add():
    data = request.form.to_dict()
    database.db.collection('career').add(data)
    trigger_rebuild()
    flash('Career milestone added!', 'success')
    return redirect(url_for('cms.career_list'))

@cms_bp.route('/career/edit/<career_id>', methods=['POST'])
@admin_required
def career_edit(career_id):
    data = request.form.to_dict()
    database.db.collection('career').document(career_id).update(data)
    trigger_rebuild()
    flash('Career milestone updated!', 'success')
    return redirect(url_for('cms.career_list'))

@cms_bp.route('/career/delete', methods=['POST'])
@admin_required
def career_delete():
    career_id = request.form.get('career_id')
    if career_id: database.db.collection('career').document(career_id).delete()
    trigger_rebuild()
    flash('Career milestone removed.', 'warning')
    return redirect(url_for('cms.career_list'))
