# Sample Kernel Driver (Intentionally Buggy)

This fictional Linux kernel module implements a minimal character device and interrupt-driven message path. It includes intentional pitfalls across atomic context, allocation failures, user pointer handling, memory ordering, module error paths, and locking mistakes for auditing practice.

File: drivers/staging/sample/sample_driver.c (excerpted snippets)

```c
#include <linux/module.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/interrupt.h>
#include <linux/vmalloc.h>
#include <linux/dma-mapping.h>
#include <linux/rcupdate.h>
#include <linux/delay.h>

#define DRV_NAME "sample_buggy"
#define DEV_NAME "sample_buggy_dev"
#define IRQ_NUM  42

struct shared_msg {
	int ready;
	char payload[64];
	int len;
};

struct sample_dev {
	spinlock_t lock;
	spinlock_t lockA;
	spinlock_t lockB;
	struct mutex ctl_mutex;

	/* DMA-related */
	void *dma_buf;
	dma_addr_t dma_handle;
	size_t dma_len;

	/* Lockless published pointer (no barriers used here intentionally) */
	struct shared_msg *shared;

	/* Device state */
	int major;
	int irq;
};

static struct sample_dev gdev;
```

---

## Function: bad_atomic_write

Atomic context violation: allocation and user-copy while holding a spinlock. Also misinterprets copy_from_user return value.

```c
/* Intentional bug: sleep-in-atomic and wrong copy_from_user handling */
static ssize_t bad_atomic_write(struct file *filp, const char __user *ubuf, size_t len, loff_t *ppos)
{
	unsigned long flags; /* but not used with irqsave here */
	char *kbuf;
	int ret = 0;

	/* Hold spinlock while allocating and copying from user (BUG) */
	spin_lock(&gdev.lock);

	/* GFP_KERNEL under spinlock can sleep (BUG) */
	kbuf = kmalloc(len, GFP_KERNEL);
	if (!kbuf) {
		spin_unlock(&gdev.lock);
		return -ENOMEM;
	}

	/* Misuse: treat copy_from_user return as negative error (BUG)
	 * copy_from_user returns bytes NOT copied.
	 */
	ret = copy_from_user(kbuf, ubuf, len);
	if (ret < 0) {
		/* Also unsafe: printk with %s using a user pointer directly (BUG) */
		printk(KERN_INFO "User said: %s\n", ubuf);
		spin_unlock(&gdev.lock);
		kfree(kbuf);
		return -EFAULT;
	}

	/* Simulate some work that can sleep (BUG) */
	msleep(10);

	spin_unlock(&gdev.lock);

	/* Pretend we wrote everything regardless of 'ret' (BUG) */
	kfree(kbuf);
	return len;
}
```

---

## Function: sample_irq_handler

Takes a spinlock in interrupt context without irqsave and does small work.

```c
/* Interrupt handler using plain spin_lock instead of spin_lock_irqsave (BUG) */
static irqreturn_t sample_irq_handler(int irq, void *cookie)
{
	/* No irqsave here (BUG) */
	spin_lock(&gdev.lock);

	/* do minimal work */
	if (gdev.shared)
		gdev.shared->ready = 1;

	spin_unlock(&gdev.lock);
	return IRQ_HANDLED;
}
```

---

## Function: allocate_dma_buf

Uses vmalloc for a DMA buffer and assumes success without mapping checks.

```c
/* Intentional bug: vmalloc used for DMA, and missing error checks */
static int allocate_dma_buf(struct sample_dev *d, size_t len)
{
	d->dma_len = len;

	/* BUG: vmalloc memory is not physically contiguous; not DMA-suitable */
	d->dma_buf = vmalloc(len);
	if (!d->dma_buf)
		return -ENOMEM;

	/* BUG: map vmalloc'ed memory directly with dma_map_single (undefined) */
	d->dma_handle = dma_map_single(NULL, d->dma_buf, d->dma_len, DMA_TO_DEVICE);
	/* Missing dma_mapping_error check (BUG) */

	return 0;
}
```

---

## Function: user_copy_write

Demonstrates unsafe printk of a user pointer and ignores copy_from_user semantics.

```c
/* Intentional bug: printk with %s on __user pointer, and copy_from_user misuse */
static long user_copy_write(struct file *f, unsigned int cmd, unsigned long arg)
{
	char __user *user_str = (char __user *)arg;
	char *kbuf;
	int not_copied;

	/* BAD: printing user pointer directly as %s can crash or leak */
	printk(KERN_INFO "Request: %s\n", user_str);

	kbuf = kzalloc(128, GFP_KERNEL);
	if (!kbuf)
		return -ENOMEM;

	/* Wrong: treat non-zero return as success (BUG) */
	not_copied = copy_from_user(kbuf, user_str, 127);
	if (not_copied == 0) {
		/* do nothing */
	} else {
		/* silently ignore the short copy (BUG) */
	}

	kfree(kbuf);
	return 0;
}
```

---

## Functions: publish_worker and fast_read

Lockless pointer publication with missing ordering; readers access without READ_ONCE. Writer does not use smp_wmb/WRITE_ONCE before publishing pointer.

```c
/* Intentional bug: publishing without barriers */
static void publish_worker(struct work_struct *ws)
{
	struct shared_msg *m;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return;

	strlcpy(m->payload, "hello", sizeof(m->payload));
	m->len = 5;
	m->ready = 1;

	/* BUG: No release barrier before publishing; no WRITE_ONCE */
	gdev.shared = m; /* publish to readers */
}

static ssize_t fast_read(struct file *filp, char __user *ubuf, size_t len, loff_t *ppos)
{
	struct shared_msg *m;

	/* BUG: No READ_ONCE, data race on pointer & fields */
	m = gdev.shared;
	if (m && m->ready && len >= m->len) {
		/* Missing check for copy_to_user return, but main point is ordering */
		if (copy_to_user(ubuf, m->payload, m->len))
			return -EFAULT;
		return m->len;
	}
	return 0;
}
```

---

## Functions: path_a, path_b, helper_relock

Inconsistent lock ordering across two paths and double-acquisition via helper causing deadlock potential. Also misuse of mutex_trylock semantics.

```c
/* Intentional bug: inconsistent lock ordering and double-acquire */
static void helper_relock(void)
{
	/* Double-acquire same lock can deadlock (BUG) */
	spin_lock(&gdev.lock);
	/* do something */
	spin_unlock(&gdev.lock);
}

static int path_a(void)
{
	/* Acquire A then B */
	spin_lock(&gdev.lockA);
	spin_lock(&gdev.lockB);

	/* Call helper that re-acquires gdev.lock while we're already holding it upstream elsewhere (BUG) */
	helper_relock();

	spin_unlock(&gdev.lockB);
	spin_unlock(&gdev.lockA);
	return 0;
}

static int path_b(void)
{
	/* Acquire B then A (inconsistent ordering vs path_a) (BUG) */
	spin_lock(&gdev.lockB);
	spin_lock(&gdev.lockA);

	spin_unlock(&gdev.lockA);
	spin_unlock(&gdev.lockB);
	return 0;
}

/* Intentional bug: misunderstanding mutex_trylock return value */
static int ctl_open(void)
{
	/* mutex_trylock returns 1 on success; here it is treated like pthreads (0=success) (BUG) */
	if (mutex_trylock(&gdev.ctl_mutex)) {
		/* Think it's error but actually got the lock; release nothing and claim busy (BUG) */
		return -EBUSY;
	}
	/* proceed without actually holding ctl_mutex */
	return 0;
}
```

---

## Function: rcu_reader_doze

Sleeping under RCU read-side critical section.

```c
/* Intentional bug: sleeping while under rcu_read_lock */
static void rcu_reader_doze(void)
{
	rcu_read_lock();
	/* This can sleep (BUG) */
	msleep(5);
	rcu_read_unlock();
}
```

---

## Module init/exit: sample_init and sample_exit

Weak error handling without proper goto-based unwind. Early failures leak earlier resources.

```c
/* Intentional bug: poor init error path; missing reverse-order cleanup */
static int __init sample_init(void)
{
	int ret;

	spin_lock_init(&gdev.lock);
	spin_lock_init(&gdev.lockA);
	spin_lock_init(&gdev.lockB);
	mutex_init(&gdev.ctl_mutex);

	gdev.irq = IRQ_NUM;

	/* Register char device (ignore error path details) */
	ret = register_chrdev(0, DEV_NAME, NULL);
	if (ret < 0)
		return ret;
	gdev.major = ret;

	/* Request IRQ without checking failure cleanup (BUG) */
	ret = request_irq(gdev.irq, sample_irq_handler, 0, DRV_NAME, &gdev);
	if (ret)
		return ret; /* leaks char device on error (BUG) */

	/* Allocate DMA buffer using buggy function (no cleanup if fails) (BUG) */
	ret = allocate_dma_buf(&gdev, 4096);
	if (ret)
		return ret; /* leaks irq and chrdev (BUG) */

	return 0;
}

static void __exit sample_exit(void)
{
	/* Not checking dma_buf existence; incomplete cleanup (BUG) */
	free_irq(gdev.irq, &gdev);
	if (gdev.dma_buf)
		vfree(gdev.dma_buf); /* the map wasn't unmapped either (BUG) */
	unregister_chrdev(gdev.major, DEV_NAME);
}
module_init(sample_init);
module_exit(sample_exit);
MODULE_LICENSE("GPL");
```

---

### Notes

- The code is intentionally flawed for educational auditing purposes.
- Code references to use in reports: bad_atomic_write, sample_irq_handler, allocate_dma_buf, user_copy_write, publish_worker, fast_read, path_a, path_b, helper_relock, ctl_open, rcu_reader_doze, sample_init, sample_exit.

---